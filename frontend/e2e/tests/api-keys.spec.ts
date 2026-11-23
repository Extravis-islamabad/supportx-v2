import { expect, request as playwrightRequest, test } from '@playwright/test';

import { CONSOLE_URL } from '../stack';
import { expectAccessible, signInAs } from './helpers';

/**
 * WP-041 journey (D-128): an admin makes a key on screen with one scope, copies it from the
 * one-time dialog, calls the API with it (allowed within its scope, refused outside it naming the
 * scope), revokes it, and its next call is refused. The key ends revoked (suite data only).
 */
test('API key: made on screen, shown once, limited to its scope, refused once revoked @smoke', async ({
  page,
}) => {
  test.setTimeout(120_000);
  const name = `E2E key ${String(Date.now())}`;
  await signInAs(page, 'admin', '/admin/api-keys');
  const panel = page.getByTestId('api-keys-admin');
  await expect(panel).toBeVisible();
  await expectAccessible(page, 'api keys');

  await page.getByTestId('api-key-new-open').click();
  const dialog = page.getByTestId('api-key-new');
  await dialog.getByTestId('api-key-name').fill(name);
  await dialog.getByTestId('api-key-scope-incidents').getByText('read', { exact: true }).click();
  await expectAccessible(page, 'new api key');
  await dialog.getByTestId('api-key-create').click();

  const shown = page.getByTestId('api-key-shown');
  // The test id is on the modal's root, a box of no size: the dialog inside is what shows.
  await expect(shown.getByRole('dialog')).toBeVisible();
  const key = await shown.getByTestId('api-key-text').inputValue();
  expect(key).toMatch(/^sxk_[0-9a-z]{26}_[0-9a-z]{26}_[A-Za-z0-9_-]{43}$/);
  await expectAccessible(page, 'api key shown once');
  await shown.getByTestId('api-key-shown-done').click();
  await expect(page.getByTestId('api-key-text')).toHaveCount(0);
  // Afterwards only the last four characters, and the scope in words.
  const row = panel.locator('tr').filter({ hasText: name });
  await expect(row).toContainText(`Ends in ${key.slice(-4)}`);
  await expect(row).toContainText('Incidents: read');
  await expect(panel).not.toContainText(key);

  // The key alone, with no session.
  const api = await playwrightRequest.newContext({
    baseURL: CONSOLE_URL,
    extraHTTPHeaders: { Authorization: `Bearer ${key}` },
  });
  try {
    expect((await api.get('/api/v1/incidents?limit=1')).status()).toBe(200);
    const outside = await api.get('/api/v1/users?limit=1');
    expect(outside.status()).toBe(403);
    expect(await outside.json()).toMatchObject({
      code: 'api_scope_missing',
      params: { scope: 'users:read' },
    });

    await row.getByTestId(`api-key-revoke-${key.slice(-4)}`).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Revoke' }).click();
    await expect(row).toContainText('Revoked');
    const refused = await api.get('/api/v1/incidents?limit=1');
    expect(refused.status()).toBe(401);
    expect(((await refused.json()) as { code: string }).code).toBe('api_key_revoked');
  } finally {
    await api.dispose();
  }
});
