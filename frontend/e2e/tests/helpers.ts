import AxeBuilder from '@axe-core/playwright';
import { expect, type Locator, type Page } from '@playwright/test';

import { passwordOf, USERS, type E2eUser } from '../stack';

/**
 * How long the first console or portal screen may take to show after the OIDC callback. The
 * callback lands on a cold app: the session is set up, then the shell loads its code, `/auth/me`
 * and the first screen's data before the user menu shows. On a busy CI runner that first load
 * takes well over Playwright's 5 s default (run 43423076862 missed it), so this one wait gets a
 * realistic bound; every later wait keeps the default.
 */
export const FIRST_LOAD_AFTER_SIGN_IN_MS = 30_000;

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
  await expect(page.getByTestId('user-menu')).toBeVisible({ timeout: FIRST_LOAD_AFTER_SIGN_IN_MS });
}

export async function signInAs(page: Page, user: E2eUser, path = '/'): Promise<void> {
  await signIn(page, USERS[user].email, passwordOf(user), path);
  // The UI language (QA BUG-04) and, since WP-042, the theme, text size, digits and Urdu style
  // are stored with the user: a test that switched a suite user to Arabic or dark must not leave
  // the next test in it. Back to the defaults (the identity provider's language).
  if (await resetLanguage(page)) {
    // The page already applied the stored theme and mirrored it in this browser; left there, the
    // app would copy it back to the server on reload (a person who never chose takes the
    // browser's) and move the user's version under the test.
    await page.evaluate(() => {
      window.localStorage.removeItem('supportx.theme_mode');
    });
    await page.reload();
    await expect(page.getByTestId('user-menu')).toBeVisible();
  }
}

/** The suite user's UI language as the server stores it (null: the identity provider's). */
export async function storedLanguage(page: Page): Promise<string | null> {
  const request = page.context().request;
  const me = (await (await request.get('/api/v1/auth/me')).json()) as { user: { id: string } };
  const user = (await (await request.get(`/api/v1/users/${me.user.id}`)).json()) as {
    ui_locale: string | null;
  };
  return user.ui_locale;
}

/** The personal choices `signInAs` puts back on the defaults (null: the default applies). */
const PERSONAL = ['ui_locale', 'theme_mode', 'text_scale', 'digits', 'urdu_script'] as const;

/** Clear the suite user's stored language and personal choices; true when any was set. */
export async function resetLanguage(page: Page): Promise<boolean> {
  const request = page.context().request;
  const me = (await (await request.get('/api/v1/auth/me')).json()) as {
    csrf_token: string;
    user: { id: string };
  };
  const path = `/api/v1/users/${me.user.id}`;
  const user = (await (await request.get(path)).json()) as Record<string, unknown> & {
    version: number;
  };
  const set = PERSONAL.filter((field) => (user[field] ?? null) !== null);
  if (set.length === 0) return false;
  const cleared = await request.patch(path, {
    data: Object.fromEntries(set.map((field) => [field, null])),
    headers: { 'If-Match': `"${String(user.version)}"`, 'X-CSRF-Token': me.csrf_token },
  });
  expect(cleared.status(), await cleared.text()).toBe(200);
  return true;
}

/** Clear the suite user's theme and text size (WP-042), so later specs start from the defaults. */
export async function resetPreferences(page: Page): Promise<void> {
  await resetLanguage(page);
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
  // Toasts are left out of the scan, not waited for: one can arrive (a notification, seconds late
  // in CI) or start fading at any moment, and a half-transparent toast fails on contrast (lane C,
  // automation.spec). Their own accessibility is checked by expectToastsAccessible
  // (toast-contrast.spec).
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
  builder = builder.exclude('.ant-message').exclude('.ant-notification');
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
 * background image cannot be measured and is skipped. Nothing is measured while a list is loading
 * or fading back in: Ant Design's overlay leaves its class first and then fades over 0.3 s, so the
 * read repeats until no overlay and no CSS transition remain, in the same tick as the measuring.
 * (Endless animations, such as a live dot, are not transitions and do not hold it up.)
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
      const settling = document
        .getAnimations()
        .some(
          (animation) => animation instanceof CSSTransition && animation.playState === 'running',
        );
      if (settling || document.querySelector('.ant-spin-blur') !== null) return null;
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

/**
 * Edit a property in place (template A, D-147): its Edit button shows only when it has the
 * keyboard's focus, so it is used as a keyboard user does, never clicked by the mouse.
 */
export async function editProperty(page: Page, testId: string): Promise<void> {
  const trigger = page.getByTestId(testId);
  await trigger.focus();
  await trigger.press('Enter');
}

/**
 * Run a record action (D-124): its button when it has one, else its entry in "More actions".
 * `bar`: the action bar's test id.
 */
export async function clickAction(
  page: Page,
  testId: string,
  bar = 'inc-operations',
): Promise<void> {
  await expect(page.getByTestId(`${bar}-more`)).toBeVisible();
  const button = page.getByTestId(testId);
  if (await button.isVisible()) {
    await button.click();
    return;
  }
  await page.getByTestId(`${bar}-more`).click();
  await page.getByTestId(`${testId}-menu`).click();
}

/** An action's entry in "More actions", with the menu open (to read its state and reason). */
export async function actionEntry(
  page: Page,
  testId: string,
  bar = 'inc-operations',
): Promise<Locator> {
  await page.getByTestId(`${bar}-more`).click();
  const entry = page.getByTestId(`${testId}-menu`);
  await expect(entry).toBeVisible();
  return entry;
}

/** Opens the Appearance panel: an item of the user menu since UI pass 3 (D-147). */
export async function openAppearance(page: Page): Promise<void> {
  await page.getByTestId('user-menu').click();
  await page.getByTestId('appearance-menu').click();
  await expect(page.getByTestId('user-menu')).toHaveAttribute('data-appearance-open', 'true');
}

/** Closes the Appearance panel (a click on the user menu button, as on any popover trigger). */
export async function closeAppearance(page: Page): Promise<void> {
  await page.getByTestId('user-menu').click();
  await expect(page.getByTestId('user-menu')).toHaveAttribute('data-appearance-open', 'false');
  await page.keyboard.press('Escape'); // the user menu the click opened
}
