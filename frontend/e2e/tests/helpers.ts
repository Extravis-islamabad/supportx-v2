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
  // An element leaving (a message fading out, a closing popup) is half transparent on its way
  // out of the page: its contrast says nothing about what users read, so wait until it is gone.
  await expect(page.locator('[class*="-leave-active"]')).toHaveCount(0, { timeout: 5_000 });
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
