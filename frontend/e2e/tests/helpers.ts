import AxeBuilder from '@axe-core/playwright';
import { expect, type Locator, type Page } from '@playwright/test';

import { passwordOf, USERS, type E2eUser } from '../stack';

/**
 * Sign in through the real BFF and Keycloak (identity-first: username page, password page).
 * Keycloak's element IDs, not its labels: it shows the password page in the user's language.
 */
export async function signIn(
  page: Page,
  email: string,
  password: string,
  path = '/',
): Promise<void> {
  await page.goto(path);
  await expect(page).toHaveURL(/\/realms\/supportx\/protocol\/openid-connect\/auth/);
  await page.locator('#username').fill(email);
  await page.locator('#kc-login').click();
  await page.locator('#password').fill(password);
  await page.locator('#kc-login').click();
  await expect(page.getByTestId('user-menu')).toBeVisible();
}

export async function signInAs(page: Page, user: E2eUser, path = '/'): Promise<void> {
  await signIn(page, USERS[user].email, passwordOf(user), path);
  // The UI language is stored with the user (QA BUG-04): a test that switched a suite user to
  // Arabic must not leave the next test in Arabic. Back to the identity provider's language.
  if (await resetLanguage(page)) {
    await page.reload();
    await expect(page.getByTestId('user-menu')).toBeVisible();
  }
}

/** Clear the suite user's stored UI language; true when there was one. */
export async function resetLanguage(page: Page): Promise<boolean> {
  const request = page.context().request;
  const me = (await (await request.get('/api/v1/auth/me')).json()) as {
    csrf_token: string;
    user: { id: string };
  };
  const path = `/api/v1/users/${me.user.id}`;
  const user = (await (await request.get(path)).json()) as {
    ui_locale: string | null;
    version: number;
  };
  if (user.ui_locale === null) return false;
  const cleared = await request.patch(path, {
    data: { ui_locale: null },
    headers: { 'If-Match': `"${String(user.version)}"`, 'X-CSRF-Token': me.csrf_token },
  });
  expect(cleared.status(), await cleared.text()).toBe(200);
  return true;
}

/**
 * axe on the current page: no serious or critical WCAG 2.1 A/AA violations. With a modal drawer
 * or dialog open only the dialog is scanned: the page behind it sits under the dimming mask and
 * is inert, so its contrast through the mask is meaningless (and depends on the fade's timing).
 * `exclude`: a region that shows something on purpose that is not for reading (a preview of a
 * colour the screen is refusing); say why at the call.
 */
export async function expectAccessible(
  page: Page,
  label: string,
  { exclude }: { exclude?: string } = {},
): Promise<void> {
  // Ant Design animates colour changes (~0.3 s); measure contrast after they settle.
  await page.waitForTimeout(600);
  // Toasts first, until they are fully gone: one can start fading while axe is scanning, so no
  // check for "leaving" before the scan closes that race, and a half-transparent toast fails on
  // contrast (lane C, automation.spec). The app has no persistent toasts; the longest lasts 4.5 s.
  await expect(page.locator('.ant-message-notice, .ant-notification-notice')).toHaveCount(0, {
    timeout: 10_000,
  });
  // Any other element leaving (a closing popup) is half transparent on its way out of the page: its
  // contrast says nothing about what users read, so wait until it is gone. "-leave" covers both
  // stages of the animation. Not a button's spinner: a button disabled as its save ends leaves it
  // stuck "leaving" for good, at no width and no opacity, so there is nothing to wait for.
  await expect(page.locator('[class*="-leave"]:not([class*="ant-btn-loading-icon"])')).toHaveCount(
    0,
    { timeout: 5_000 },
  );
  let builder = new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']);
  if ((await page.locator('[aria-modal="true"]:visible').count()) > 0) {
    builder = builder.include('[aria-modal="true"]');
  }
  if (exclude !== undefined) builder = builder.exclude(exclude);
  const results = await builder.analyze();
  const blocking = results.violations.filter(
    (v) => v.impact === 'serious' || v.impact === 'critical',
  );
  expect(
    blocking.map(
      (v) =>
        `${v.id} (${String(v.impact)}): ${v.nodes
          .map((n) => n.target.join(' '))
          .slice(0, 3)
          .join(' | ')}`,
    ),
    `axe violations on ${label}`,
  ).toEqual([]);
}

type Rgba = [number, number, number, number];

/** WCAG contrast ratio of two opaque colours. */
function contrastRatio(foreground: Rgba, background: Rgba): number {
  const luminance = ([r, g, b]: Rgba): number => {
    const [lr = 0, lg = 0, lb = 0] = [r, g, b].map((value) => {
      const unit = value / 255;
      return unit <= 0.03928 ? unit / 12.92 : ((unit + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb;
  };
  const [dark = 0, light = 0] = [luminance(foreground), luminance(background)].sort(
    (x, y) => x - y,
  );
  return (light + 0.05) / (dark + 0.05);
}

/**
 * WCAG AA text contrast measured from computed colours, for what axe cannot see: its
 * color-contrast rule takes Arabic-script text for an icon ligature and skips it, so "axe clean"
 * in Arabic or Urdu says nothing about contrast (docs/architecture/testing.md). Walks the visible
 * text under `root`, blends each colour and its opacity over the real backgrounds behind it, and
 * asks 4.5:1, or 3:1 for large text. Disabled controls are exempt (WCAG 1.4.3); text over a
 * background image cannot be measured and is skipped. A list reloading sits under a half-opaque
 * overlay: it is read again until the overlay has gone, in the same tick as the measuring, so a
 * reload can never be measured as low contrast.
 */
export async function expectTextContrast(
  page: Page,
  label: string,
  { root = 'main', atLeast = 1 }: { root?: string; atLeast?: number } = {},
): Promise<void> {
  interface Measured {
    text: string;
    colour: Rgba;
    background: Rgba;
    large: boolean;
  }
  const read = (): Promise<Measured[] | null> =>
    page.evaluate((selector) => {
      if (document.querySelector('.ant-spin-blur') !== null) return null;
      const parse = (colour: string): Rgba => {
        const [r = 0, g = 0, b = 0, a = 1] = (colour.match(/[\d.]+/g) ?? []).map(Number);
        return [r, g, b, a];
      };
      const over = (front: Rgba, back: Rgba): Rgba => {
        const [r, g, b, a] = front;
        return [r * a + back[0] * (1 - a), g * a + back[1] * (1 - a), b * a + back[2] * (1 - a), 1];
      };
      const found: Measured[] = [];
      for (const start of document.querySelectorAll(selector)) {
        const walker = document.createTreeWalker(start, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
          const text = node.textContent?.trim() ?? '';
          const element = node.parentElement;
          if (text === '' || element === null || element.getClientRects().length === 0) continue;
          const style = getComputedStyle(element);
          if (style.visibility !== 'visible') continue;
          if (element.closest('[disabled], [aria-disabled="true"], [class*="-disabled"]')) continue;
          // Everything behind the text, nearest first, down to the first opaque layer.
          const layers: Rgba[] = [];
          let opacity = 1;
          let image = false;
          for (let at: Element | null = element; at !== null; at = at.parentElement) {
            const own = getComputedStyle(at);
            opacity *= Number(own.opacity);
            if (own.backgroundImage !== 'none') image = true;
            const layer = parse(own.backgroundColor);
            if (layer[3] > 0 && layers.at(-1)?.[3] !== 1) layers.push(layer);
          }
          if (image || opacity === 0) continue;
          let background: Rgba = [255, 255, 255, 1];
          for (const layer of layers.reverse()) background = over(layer, background);
          const [r, g, b, a] = parse(style.color);
          const size = parseFloat(style.fontSize);
          const bold = Number(style.fontWeight) >= 700;
          found.push({
            text: text.slice(0, 40),
            colour: over([r, g, b, a * opacity], background),
            background,
            large: size >= 24 || (bold && size >= 18.66),
          });
        }
      }
      return found;
    }, root);
  const latest: { found: Measured[] | null } = { found: null };
  await expect
    .poll(
      async () => {
        latest.found = await read();
        return latest.found !== null;
      },
      { message: `${label} finished loading`, timeout: 10_000 },
    )
    .toBe(true);
  const measured = latest.found ?? [];
  expect(measured.length, `text measured on ${label}`).toBeGreaterThanOrEqual(atLeast);
  const low = measured.flatMap((item) => {
    const ratio = contrastRatio(item.colour, item.background);
    return ratio < (item.large ? 3 : 4.5) ? [`${ratio.toFixed(2)}:1 "${item.text}"`] : [];
  });
  expect([...new Set(low)], `low contrast on ${label}`).toEqual([]);
}

/**
 * Toasts held open on the dev page, fully shown (`expectAccessible` waits until toasts have gone).
 * Every animation must have finished first, so a half-faded toast cannot pass or fail by timing.
 */
export async function expectToastsAccessible(page: Page, label: string): Promise<void> {
  await expect(page.locator('.ant-message-notice')).toHaveCount(4);
  await page.evaluate(async () => {
    const shown = [...document.querySelectorAll('.ant-message')];
    const animations = shown.flatMap((toast) => toast.getAnimations({ subtree: true }));
    await Promise.all(animations.map((animation) => animation.finished));
  });
  const kinds = await page
    .locator('.ant-message-custom-content')
    .evaluateAll((toasts: Element[]) => toasts.map((toast) => toast.getAttribute('class')));
  expect(new Set(kinds).size, `four kinds on ${label}`).toBe(4);
  await expectTextContrast(page, label, { root: '.ant-message-notice-content', atLeast: 4 });
  const results = await new AxeBuilder({ page })
    .include('.ant-message')
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`),
    `axe violations on ${label}`,
  ).toEqual([]);
}

interface RoleRow {
  id: string;
  key: string;
  name: string;
  is_system: boolean;
  user_count: number;
  version: number;
}

/**
 * Delete the suite's own custom roles (named "E2E …") left by an earlier, interrupted run,
 * through the API with the signed-in admin's session. Holders move to the Requester role.
 */
export async function deleteE2eRoles(admin: Page): Promise<number> {
  const request = admin.context().request;
  const me = (await (await request.get('/api/v1/auth/me')).json()) as { csrf_token: string };
  const roles = (await (await request.get('/api/v1/roles')).json()) as RoleRow[];
  const requester = roles.find((role) => role.key === 'requester');
  let deleted = 0;
  for (const role of roles.filter((r) => !r.is_system && r.name.startsWith('E2E '))) {
    const query =
      role.user_count > 0 && requester !== undefined ? `?reassign_to=${requester.id}` : '';
    const response = await request.delete(`/api/v1/roles/${role.id}${query}`, {
      headers: { 'If-Match': `"${String(role.version)}"`, 'X-CSRF-Token': me.csrf_token },
    });
    expect(response.status(), await response.text()).toBe(204);
    deleted += 1;
  }
  return deleted;
}

/** The main navigation, whatever the user's layout (top bar, side bar, compact side bar). */
export function mainNav(page: Page) {
  return page.locator('nav[data-items]');
}

/** Section keys the navigation offers (independent of layout and of what fits on screen). */
export async function navItems(page: Page): Promise<string[]> {
  const items = await mainNav(page).getAttribute('data-items');
  return (items ?? '').split(' ').filter(Boolean);
}

/**
 * Open a section by its visible label: directly when it is on screen, else through the top
 * bar's "More" menu (sections that do not fit the width).
 */
export async function goToSection(page: Page, label: string): Promise<void> {
  // Items that overflowed into "More" stay in the DOM, transparent and aria-hidden.
  const direct = mainNav(page)
    .locator('li[role="menuitem"]:not([aria-hidden="true"])')
    .getByText(label, { exact: true });
  if ((await direct.count()) > 0) {
    await direct.first().click();
    return;
  }
  await mainNav(page).getByTestId('nav-more').click();
  await page
    .locator('.ant-menu-submenu-popup')
    .getByText(label, { exact: true })
    .filter({ visible: true })
    .first()
    .click();
}

/**
 * Wait until the web fonts have loaded and two frames have painted. Layout measured earlier
 * can be a few pixels off: a fallback font has other metrics (a 3.4 px miss on CI, #80).
 */
export async function settledLayout(page: Page): Promise<void> {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise<void>((resolve) => {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          resolve();
        });
      });
    });
  });
}

/** A box measured once fonts are in and it stopped moving (the same twice in a row). */
export async function settledBox(
  locator: Locator,
): Promise<Awaited<ReturnType<Locator['boundingBox']>>> {
  const page = locator.page();
  await settledLayout(page);
  let previous = await locator.boundingBox();
  for (let attempt = 0; attempt < 20; attempt += 1) {
    await page.waitForTimeout(50);
    const next = await locator.boundingBox();
    if (JSON.stringify(next) === JSON.stringify(previous)) return next;
    previous = next;
  }
  return previous;
}

/**
 * Open an Ant Design Select and wait until its list has finished opening: clicking an option
 * while the list still slides in can scroll the virtual list so the option never renders (lane
 * B, WP-039; a banner above shifts the layout enough to expose it).
 */
export async function openSelect(page: Page, testId: string) {
  await page.getByTestId(testId).click();
  // The list just closed may still be leaving.
  const dropdown = page.locator('.ant-select-dropdown:visible:not([class*="-leave"])');
  await expect(dropdown).not.toHaveClass(/ant-slide-up-(appear|enter)/);
  return dropdown;
}
