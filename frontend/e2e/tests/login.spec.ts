import { expect, test } from '@playwright/test';

/** Dev test user from deploy/compose/keycloak/supportx-realm.json (documented in docs/dev-setup.md). */
const TECH = { email: 'tech@demo.test', password: 'Tech-Demo-2026!', name: 'Tariq Technician' };

test('a technician logs in to the console, sees name and tenant, and logs out', async ({
  page,
}) => {
  // Not logged in: the console sends the browser through the BFF to Keycloak.
  await page.goto('/');
  await expect(page).toHaveURL(/\/realms\/supportx\/protocol\/openid-connect\/auth/);

  // Keycloak Organizations: identity-first login (username page, then password page).
  await page.getByLabel(/username or email/i).fill(TECH.email);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.getByLabel('Password', { exact: true }).fill(TECH.password);
  await page.getByRole('button', { name: /sign in/i }).click();

  // Back in the console with a session.
  await expect(page).toHaveURL(/localhost:5173\/$/);
  await expect(page.getByTestId('user-name')).toHaveText(TECH.name);
  await expect(page.getByTestId('tenant-name')).toHaveText('Demo Company');
  const cookies = await page.context().cookies();
  const session = cookies.find((cookie) => cookie.name === 'supportx_session');
  expect(session?.httpOnly).toBe(true);
  expect(session?.sameSite).toBe('Lax');
  expect(await page.evaluate(() => document.cookie)).not.toContain('supportx_session');

  // Logout ends the BFF session and the Keycloak session: we are asked for credentials again.
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/realms\/supportx\/protocol\/openid-connect\/auth/);
  await expect(page.getByLabel(/username or email/i)).toBeVisible();
  expect(
    (await page.context().cookies()).find((c) => c.name === 'supportx_session'),
  ).toBeUndefined();
});
