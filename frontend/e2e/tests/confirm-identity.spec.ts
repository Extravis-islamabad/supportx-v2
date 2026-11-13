import { expect, test, type Page } from '@playwright/test';

import { passwordOf, USERS } from '../stack';
import { expectAccessible, signInAs } from './helpers';

/**
 * WP-057 S2a, REQ-SEC-027 AC1, against the real BFF and Keycloak: a sensitive change refused for
 * want of a recent sign-in is confirmed in a pop-up (Keycloak asks for the password again,
 * `prompt=login`), and the change goes ahead within 5 seconds of confirming, with no new session.
 *
 * Only the first refusal is staged: the suite cannot wait out the 10-minute window. The server's
 * own refusal, the stale and wrong-person cases and the sign-in log are API tests
 * (tests/db/test_confirm_identity.py). Everything after the refusal is real: the dialog, the
 * pop-up's Keycloak sign-in, /confirmed, the same-origin channel and the retry.
 */

/** Keycloak's re-authentication page: the address may be asked again (identity-first), then the password. */
async function confirmAtKeycloak(popup: Page, email: string, password: string): Promise<void> {
  await expect(popup).toHaveURL(/\/realms\/supportx\/protocol\/openid-connect\/auth/);
  const address = popup.locator('#username');
  if (await address.isVisible()) {
    await address.fill(email);
    await popup.locator('#kc-login').click();
  }
  await popup.locator('#password').fill(password);
  await popup.locator('#kc-login').click();
}

test('a refused sensitive change goes ahead once you confirm it is you (REQ-SEC-027 AC1)', async ({
  page,
  context,
}) => {
  test.setTimeout(120_000);
  const name = `E2E confirm ${String(Date.now())}`;
  await signInAs(page, 'admin', '/admin/api-keys');
  // supportx_session locally, __Host-supportx_session behind TLS (bff/cookies.py).
  const cookie = (await context.cookies()).find((c) => c.name.endsWith('supportx_session'));
  expect(cookie).toBeDefined();

  // The first create is refused as the server refuses a stale sign-in; the retry reaches the API.
  let refused = 0;
  const sent: { retry: string | null; key: string | null }[] = [];
  await page.route('**/api/v1/api-keys', async (route) => {
    const request = route.request();
    if (request.method() !== 'POST') return route.fallback();
    sent.push({
      retry: request.headers()['x-supportx-confirmed-retry'] ?? null,
      key: request.headers()['idempotency-key'] ?? null,
    });
    if (refused === 0) {
      refused += 1;
      return route.fulfill({
        status: 403,
        contentType: 'application/problem+json',
        body: JSON.stringify({
          type: 'about:blank',
          title: 'Forbidden',
          status: 403,
          code: 'reauth_required',
          params: { max_age_minutes: 10 },
        }),
      });
    }
    return route.fallback();
  });

  await page.getByTestId('api-key-new-open').click();
  const dialog = page.getByTestId('api-key-new');
  await dialog.getByTestId('api-key-name').fill(name);
  await dialog.getByTestId('api-key-scope-incidents').getByText('read', { exact: true }).click();
  await dialog.getByTestId('api-key-create').click();

  // Asked first; the pop-up opens from that click.
  await expect(page.getByTestId('reauth-ask')).toBeVisible();
  await expectAccessible(page, 'confirm it is you');
  const opened = context.waitForEvent('page');
  await page.getByTestId('reauth-confirm').click();
  const popup = await opened;
  await expect(page.getByTestId('reauth-waiting')).toBeVisible();

  await confirmAtKeycloak(popup, USERS.admin.email, passwordOf('admin'));
  const confirmedAt = Date.now();
  // The change goes ahead: the new key is shown once (AC1: within 5 seconds of confirming).
  const shown = page.getByTestId('api-key-shown');
  await expect(shown.getByRole('dialog')).toBeVisible({ timeout: 5_000 });
  expect(Date.now() - confirmedAt).toBeLessThan(5_000);
  // The pop-up closed itself, or (where a browser refuses) says it may be closed.
  if (!popup.isClosed()) await expect(popup).toHaveURL(/\/confirmed\?/);
  // Sent twice: the same idempotency key, the second marked as the one retry.
  expect(sent).toHaveLength(2);
  expect(sent[1]?.retry).toBe('1');
  expect(sent[1]?.key).toBe(sent[0]?.key);
  // The same session: confirming refreshed it, never replaced it.
  const after = (await context.cookies()).find((c) => c.name === cookie?.name);
  expect(after?.value).toBe(cookie?.value);

  // Tidy up the suite's key.
  const key = await shown.getByTestId('api-key-text').inputValue();
  await shown.getByTestId('api-key-shown-done').click();
  const row = page.getByTestId('api-keys-admin').locator('tr').filter({ hasText: name });
  await row.getByTestId(`api-key-revoke-${key.slice(-4)}`).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Revoke' }).click();
  await expect(row).toContainText('Revoked');
});
