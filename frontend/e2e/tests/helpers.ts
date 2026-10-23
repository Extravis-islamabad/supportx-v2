import AxeBuilder from '@axe-core/playwright';
import { expect, type Page } from '@playwright/test';

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
}

/** axe on the current page: no serious or critical WCAG 2.1 A/AA violations. */
export async function expectAccessible(page: Page, label: string): Promise<void> {
  // Ant Design animates colour changes (~0.3 s); measure contrast after they settle.
  await page.waitForTimeout(600);
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
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
