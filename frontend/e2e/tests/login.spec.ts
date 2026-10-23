import { expect, test } from '@playwright/test';

import { CONSOLE_URL, SEEDED } from '../stack';
import { signIn } from './helpers';

test('a technician logs in to the console, sees name and tenant, and logs out', async ({
  page,
}) => {
  await signIn(page, SEEDED.tech.email, SEEDED.tech.password);
  await expect(page).toHaveURL(`${CONSOLE_URL}/`);
  await expect(page.getByTestId('user-name')).toHaveText('Tariq Technician');
  await expect(page.getByTestId('tenant-name')).toHaveText('Demo Company');
  const cookies = await page.context().cookies();
  const session = cookies.find((cookie) => cookie.name === 'supportx_session');
  expect(session?.httpOnly).toBe(true);
  expect(session?.sameSite).toBe('Lax');
  expect(await page.evaluate(() => document.cookie)).not.toContain('supportx_session');

  // Logout ends the BFF session and the Keycloak session: we are asked for credentials again.
  await page.getByTestId('user-menu').click();
  await page.getByText('Sign out').click();
  await expect(page).toHaveURL(/\/realms\/supportx\/protocol\/openid-connect\/auth/);
  await expect(page.getByLabel(/username or email/i)).toBeVisible();
  expect(
    (await page.context().cookies()).find((c) => c.name === 'supportx_session'),
  ).toBeUndefined();
});
