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
