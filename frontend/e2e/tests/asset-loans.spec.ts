import { expect, test, type Browser, type Page } from '@playwright/test';

import { PORTAL_URL, USERS } from '../stack';
import { expectAccessible, signInAs } from './helpers';

const LIVE = { timeout: 5_000 };

interface Me {
  csrf_token: string;
}

async function open(browser: Browser, user: 'admin' | 'limited', path: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, user, path);
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected', LIVE);
  return { context, page };
}

/** A fresh asset of its own product (suite data only), made through the public API. */
async function newAsset(page: Page, name: string): Promise<{ id: string }> {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as Me;
  const headers = { 'X-CSRF-Token': me.csrf_token };
  const types = (await (await page.request.get('/api/v1/assets/product-types')).json()) as {
    id: string;
    api_name: string;
  }[];
  const laptop = types.find((x) => x.api_name === 'laptop');
  expect(laptop, 'the catalogue has the laptop type').toBeDefined();
  const product = await page.request.post('/api/v1/assets/products', {
    data: { product_type_id: laptop?.id, name: `${name} model` },
    headers: { ...headers, 'Idempotency-Key': crypto.randomUUID() },
  });
  expect(product.status(), await product.text()).toBe(201);
  const made = await page.request.post('/api/v1/assets', {
    data: { name, product_id: ((await product.json()) as { id: string }).id },
    headers: { ...headers, 'Idempotency-Key': crypto.randomUUID() },
  });
  expect(made.status(), await made.text()).toBe(201);
  return (await made.json()) as { id: string };
}

/**
 * WP-049a s5 journey (REQ-AST-029..031): an admin marks an asset loanable from the list, lends it
 * to a requester from the loan register, the requester sees it in the portal with its due date
 * (live), and the admin takes it back to stock: the loan leaves the register and the portal
 * drops it, both without a refresh.
 */
test('asset loan: loanable in bulk, lent, due in the portal, taken back, all live', async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const name = `E2E loan laptop ${String(Date.now())}`;
  const admin = await open(browser, 'admin', '/assets');
  const borrower = await open(browser, 'limited', `${PORTAL_URL}/my-assets`);
  try {
    const asset = await newAsset(admin.page, name);

    // The list: search it, select it, make it loanable.
    await admin.page.goto('/assets');
    await admin.page.getByTestId('assets-search').fill(name);
    const row = admin.page.locator('tr').filter({ hasText: name });
    await expect(row).toBeVisible();
    await row.getByRole('checkbox').check();
    await admin.page.getByTestId('assets-make-loanable').click();
    await expect(admin.page.getByText('Marked as loanable')).toBeVisible();

    // The register: a new loan to the requester.
    await admin.page.getByTestId('assets-loans-link').click();
    await expect(admin.page.getByTestId('asset-loans')).toBeVisible();
    await admin.page.getByTestId('asset-loan-new-open').click();
    const dialog = admin.page.getByTestId('asset-loan-new');
    await dialog.getByTestId('asset-loan-borrower').click();
    await admin.page.keyboard.type(USERS.limited.first);
    // The visible item: Ant Design's role="option" copy is hidden and holds the id as its text
    // (the person's name and email are its aria-label), so a text filter never matched it.
    await admin.page
      .locator('.ant-select-item-option', { hasText: USERS.limited.email })
      .first()
      .click();
    await dialog.getByTestId('asset-loan-assets').click();
    await admin.page.keyboard.type(name);
    await admin.page.locator('.ant-select-item-option', { hasText: name }).first().click();
    await admin.page.keyboard.press('Escape');
    await expectAccessible(admin.page, 'new loan');
    await dialog.getByRole('button', { name: 'Lend' }).click();
    await expect(dialog.getByRole('dialog')).toHaveCount(0);
    const loan = admin.page.getByTestId('asset-loans').locator('tr').filter({ hasText: name });
    await expect(loan).toContainText(`${USERS.limited.first} ${USERS.limited.last}`);
    await expect(loan).toContainText('Open');
    await expectAccessible(admin.page, 'loan register');

    // The borrower's portal shows it, with when it is due, without a refresh.
    const mine = borrower.page.getByTestId(`my-asset-due-${asset.id}`);
    await expect(mine).toContainText('Due back', LIVE);

    // Back to stock: the loan closes and leaves the register; the portal drops the asset.
    await loan.getByRole('button', { name: 'Take back' }).click();
    const back = admin.page.getByTestId('asset-loan-return');
    await back.getByRole('button', { name: 'Take back' }).click();
    await expect(loan).toHaveCount(0, LIVE);
    await expect(borrower.page.getByTestId(`my-asset-${asset.id}`)).toHaveCount(0, LIVE);
  } finally {
    await admin.context.close();
    await borrower.context.close();
  }
});
