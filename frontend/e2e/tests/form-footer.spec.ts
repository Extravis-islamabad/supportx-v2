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
    // The last field of the form, focused the way Tab focuses it (the browser scrolls it in).
    // Ant Design puts the test ID on the input or on its wrapper, by version: either way.
    const last = page
      .locator('input[data-testid="ann-until"], [data-testid="ann-until"] input')
      .first();
    await last.focus();
    await expect(last).toBeFocused();
    const field = await last.boundingBox();
    const bar = await footer.boundingBox();
    expect(field).not.toBeNull();
    expect(bar).not.toBeNull();
    if (field === null || bar === null) return;
    // Fully in the window and above the bar.
    expect(field.y).toBeGreaterThanOrEqual(0);
    expect(field.y + field.height).toBeLessThanOrEqual(bar.y);
  });
}
