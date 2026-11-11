import { expect, test } from '@playwright/test';

import { signInAs } from './helpers';

// QA-2026-11-11 V-01 and lane B's #402 review: the full-page screenshots draw the sticky footer
// bar where it ends up, so they can no longer catch a bar that covers a field. This does: a
// long form's last field, reached by the keyboard, sits clear above the bar, on a phone and on
// a laptop. Nothing is saved.

for (const size of [
  { width: 390, height: 844 },
  { width: 1280, height: 800 },
]) {
  test(`a field reached by the keyboard is never behind the footer bar (${String(size.width)} px)`, async ({
    page,
  }) => {
    await page.setViewportSize(size);
    await signInAs(page, 'admin', '/announcements/new');
    const footer = page.locator('[data-sticky-footer]').first();
    await expect(footer).toBeVisible();
    // The last field of the form, reached by a real Tab from the field before it: the bug was
    // on the keyboard path (lane B's #421 review).
    const input = (testId: string) =>
      page.locator(`input[data-testid="${testId}"], [data-testid="${testId}"] input`).first();
    const last = input('ann-until');
    await input('ann-from').focus();
    await page.keyboard.press('Tab');
    await expect(last).toBeFocused();
    // Measured once the scroll and the bar's size watcher have settled (slow runners).
    await expect
      .poll(async () => {
        const field = await last.boundingBox();
        const bar = await footer.boundingBox();
        if (field === null || bar === null) return 'not laid out';
        if (field.y < 0) return 'above the window';
        return field.y + field.height <= bar.y ? 'clear' : 'behind the bar';
      })
      .toBe('clear');
  });
}
