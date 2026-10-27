import { expect, test, type Page } from '@playwright/test';

import { settledLayout, signInAs } from './helpers';

/**
 * WP-020c QA findings that need a real browser (~/Desktop/qa-wp020c/QA-REPORT.md): BUG-03 no
 * sideways scrolling at phone width on any admin screen; C6 the tag picker closes after a tag
 * is added. Read-only on the tenant: nothing is saved.
 */

const ADMIN_SCREENS = [
  '/admin/users',
  '/admin/roles',
  '/admin/audit?tab=log',
  '/admin/audit?tab=integrity',
  '/admin/audit?tab=exports',
  '/admin/audit?tab=archives',
  '/admin/audit?tab=settings',
  '/admin/files',
  '/admin/incidents/general',
  '/admin/incidents/templates',
  '/admin/incidents/custom-fields',
  '/admin/incidents/statuses',
  '/admin/incidents/reasons',
  '/admin/incidents/priority',
  '/admin/incidents/categories',
  '/admin/incidents/levels',
  '/admin/incidents/closure-codes',
  '/admin/incidents/reply-templates',
  '/admin/automation/business-rules',
  '/admin/automation/routing',
];

/** Elements wider than the window (what makes the page scroll sideways). */
async function overflow(page: Page): Promise<{ page: number; window: number; culprits: string[] }> {
  await settledLayout(page);
  return page.evaluate(() => {
    const width = window.innerWidth;
    const culprits = [...document.querySelectorAll<HTMLElement>('body *')]
      .filter((el) => {
        const box = el.getBoundingClientRect();
        return box.width > 0 && box.right > width + 1 && getComputedStyle(el).position !== 'fixed';
      })
      .filter((el) => !el.closest('.ant-table-content, .ant-table-body')) // tables scroll inside
      .slice(0, 5)
      .map((el) => `${el.tagName.toLowerCase()}.${(el.getAttribute('class') ?? '').slice(0, 60)}`);
    return { page: document.documentElement.scrollWidth, window: width, culprits };
  });
}

test('BUG-03: no admin screen scrolls sideways at 390 px', async ({ page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await signInAs(page, 'admin', '/admin/users');
  const problems: string[] = [];
  const check = async (label: string) => {
    const found = await overflow(page);
    if (found.page > found.window) {
      problems.push(
        `${label}: ${String(found.page)} > ${String(found.window)} ${found.culprits.join(', ')}`,
      );
    }
  };
  for (const path of ADMIN_SCREENS) {
    await page.goto(path);
    await expect(page.getByTestId('user-menu')).toBeVisible();
    await page.waitForLoadState('networkidle');
    await check(path);
  }
  // Drawers and dialogs too.
  await page.goto('/admin/incidents/templates');
  await page.getByTestId('tpl-admin-new').click();
  await expect(page.getByTestId('tpl-editor')).toBeVisible();
  await check('template editor');
  await page.goto('/admin/incidents/categories');
  await page.getByTestId('cat-add-root').click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await check('category dialog');
  expect(problems).toEqual([]);
});

test('C6: the tag picker closes once a tag is added', async ({ page }) => {
  await signInAs(page, 'admin', '/incidents/new');
  const tags = page.getByTestId('inc-tags');
  await tags.click();
  await page.keyboard.type('vip');
  await page.keyboard.press('Enter');
  await expect(tags).toContainText('vip');
  // Closed at once, not after a blur: nothing covers the buttons below.
  await expect(page.locator('.ant-select-dropdown:visible')).toHaveCount(0, { timeout: 500 });
  await page.keyboard.type('urgent');
  await page.keyboard.press('Enter');
  await expect(tags).toContainText('urgent');
  await expect(page.locator('.ant-select-dropdown:visible')).toHaveCount(0, { timeout: 500 });
  await expect(page.getByTestId('inc-save')).toBeVisible();
});
