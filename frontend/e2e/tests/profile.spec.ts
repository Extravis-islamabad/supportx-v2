import { expect, test } from '@playwright/test';

import { signInAs } from './helpers';

test('My profile: save, inline field error, and the conflict dialog across two browsers', async ({
  browser,
}) => {
  const first = await browser.newContext();
  const second = await browser.newContext();
  const a = await first.newPage();
  const b = await second.newPage();
  await signInAs(a, 'tech', '/profile');
  await signInAs(b, 'tech', '/profile');
  const stamp = String(Date.now());

  // An invalid time zone: the API's field error appears under the field, translated.
  await a.getByTestId('profile-time-zone').fill('Mars/Olympus');
  await a.getByTestId('profile-save').click();
  await expect(a.getByTestId('error-time_zone')).toHaveText(
    'This is not one of the allowed values.',
  );
  await a.getByTestId('profile-time-zone').fill('Asia/Dubai');

  // A saves first.
  await a.getByTestId('profile-signature').fill(`From A ${stamp}`);
  await a.getByTestId('profile-save').click();
  await expect(a.getByText('Your preferences were saved.')).toBeVisible();

  // B still has the old version open: its save meets the conflict dialog.
  await b.getByTestId('profile-signature').fill(`From B ${stamp}`);
  await b.getByTestId('profile-save').click();
  const dialog = b.getByRole('dialog');
  await expect(dialog.getByText('Someone else changed this')).toBeVisible();
  await b.screenshot({ path: 'test-results/conflict-dialog.png' });
  await dialog.getByRole('button', { name: 'Keep my changes' }).click();
  await expect(b.getByText('Your preferences were saved.')).toBeVisible();

  // A reloads and sees B's version; A's time zone survived because B saved on top of it.
  await a.reload();
  await expect(a.getByTestId('profile-signature')).toHaveValue(`From B ${stamp}`);
  await expect(a.getByTestId('profile-time-zone')).toHaveValue('Asia/Dubai');

  // "Reload their version" discards local edits.
  await a.getByTestId('profile-signature').fill(`Stale ${stamp}`);
  await b.getByTestId('profile-signature').fill(`Newest ${stamp}`);
  await b.getByTestId('profile-save').click();
  await expect(b.getByText('Your preferences were saved.').last()).toBeVisible();
  await a.getByTestId('profile-save').click();
  await a.getByRole('dialog').getByRole('button', { name: 'Reload their version' }).click();
  await expect(a.getByTestId('profile-signature')).toHaveValue(`Newest ${stamp}`);
  await first.close();
  await second.close();
});
