import AxeBuilder from '@axe-core/playwright';
import { chromium } from '@playwright/test';

const OUT = '/private/tmp/claude-501/-Users-haiderzaidi-Extravis-supportx-v2/bae26076-1f7a-4867-9937-87165ed043a6/scratchpad/wp039shots';
const APP = 'http://localhost:5183';
const note = (step, ok, detail = '') => console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step} ${detail}`);
const axe = async (page) => {
  await page.waitForTimeout(700);
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  return r.violations.filter((v) => ['serious', 'critical'].includes(v.impact)).map((v) => `${v.id}: ${v.nodes.slice(0, 2).map((n) => n.target.join(' ')).join(' | ')}`);
};
const browser = await chromium.launch();
const admin = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
try {
  await admin.goto(`${APP}/admin/security`);
  await admin.locator('#username').fill('admin@demo.test');
  await admin.locator('#kc-login').click();
  await admin.locator('#password').fill('Admin-Demo-2026!');
  await admin.locator('#kc-login').click();
  await admin.getByTestId('admin-security').waitFor({ timeout: 30000 });
  note('admin opens Sign-in and security', true);
  for (const theme of ['light', 'dark', 'high_contrast']) {
    await admin.evaluate((v) => localStorage.setItem('supportx.theme_mode', v), theme);
    await admin.reload();
    await admin.getByTestId('security-sso').waitFor();
    const bad = await axe(admin);
    note(`axe security page (${theme})`, bad.length === 0, bad.join(' ; ') || 'clean');
  }
  await admin.evaluate(() => localStorage.setItem('supportx.theme_mode', 'light'));
  await admin.reload();
  const csrf = (await (await admin.request.get(`${APP}/api/v1/auth/me`)).json()).csrf_token;
  const dept = await admin.request.post(`${APP}/api/v1/organization/departments`, { data: { name: 'Finance', code: 'fin' }, headers: { 'X-CSRF-Token': csrf } });
  note('a Finance department exists for the mapping', [201, 409, 422].includes(dept.status()), String(dept.status()));
  await admin.getByTestId('sso-add').click();
  const editor = admin.getByTestId('sso-editor');
  await editor.getByTestId('sso-preset').getByText('Other OpenID Connect').click();
  await editor.getByTestId('sso-display_name').fill('Acme sign-in');
  await editor.getByRole('combobox').fill('acme.test,');
  await editor.getByTestId('sso-issuer').fill('http://127.0.0.1:28183/realms/acme');
  await editor.getByTestId('sso-client_id').fill('supportx-broker');
  await editor.getByTestId('sso-client_secret').fill('wrong-secret');
  await editor.getByText('Attributes').click();
  await editor.getByTestId('sso-map-department').fill('department');
  await editor.getByTestId('sso-email_redirect').click();
  await admin.screenshot({ path: `${OUT}/01-editor.png`, fullPage: true });
  await admin.getByTestId('sso-save').click();
  const wrong = await admin.getByTestId('sso-client_secret-field').getByRole('alert').innerText({ timeout: 10000 }).catch(() => '(none)');
  note('a wrong client secret is refused at the field', wrong.includes('refused'), wrong);
  await editor.getByTestId('sso-client_secret').fill('broker-secret');
  await admin.getByTestId('sso-save').click();
  const row = admin.getByTestId('sso-Acme sign-in');
  await row.waitFor({ timeout: 15000 });
  note('saved in draft', (await row.getByTestId('sso-state').innerText()) === 'Draft', (await row.innerText()).replace(/\n/g, ' / ').slice(0, 300));
  await admin.screenshot({ path: `${OUT}/02-draft.png`, fullPage: true });
  const [startResponse] = await Promise.all([
    admin.waitForResponse((r) => r.url().includes('/tests') && r.request().method() === 'POST'),
    row.getByTestId('sso-test').click(),
  ]);
  const testUrl = (await startResponse.json()).url;
  const dialog = admin.getByTestId('sso-test-dialog');
  await dialog.getByTestId('sso-test-link').waitFor();
  note('the test link for a private window is offered', testUrl.includes('kc_idp_hint='), testUrl.slice(0, 90));
  await admin.screenshot({ path: `${OUT}/03a-test-link.png` });
  // The private window: a fresh browser context opening the same test link.
  const privateWindow = await (await browser.newContext()).newPage();
  await privateWindow.goto(testUrl);
  await privateWindow.locator('#username').fill('alice@acme.test');
  await privateWindow.locator('#password').fill('Alice-Acme-2026!');
  await privateWindow.locator('#kc-login').click();
  await privateWindow.getByTestId('sso-test-done').waitFor({ timeout: 20000 }).catch(() => undefined);
  note('the private window lands on the done page without a session', privateWindow.url().endsWith('/sso-test-done'), privateWindow.url());
  await privateWindow.screenshot({ path: `${OUT}/03b-private-done.png` });
  const passed = await dialog.getByTestId('sso-test-passed').waitFor({ timeout: 15000 }).then(() => true).catch(() => false);
  await admin.screenshot({ path: `${OUT}/03-test-result.png` });
  note('the test passed and shows what came through', passed, (await dialog.innerText()).replace(/\n/g, ' / ').slice(0, 300));
  const bad = await axe(admin);
  note('axe test dialog', bad.length === 0, bad.join(' ; ') || 'clean');
  await dialog.getByRole('button', { name: 'Close' }).first().click();
  const me = await (await admin.request.get(`${APP}/api/v1/auth/me`)).json();
  note('the admin is still signed in as the admin after the test', me.user?.email === 'admin@demo.test', me.user?.email);
  await row.getByTestId('sso-switch').click();
  await admin.waitForTimeout(1500);
  note('switched on', (await row.getByTestId('sso-state').innerText()) === 'On');
  // Alice signs in for real in a fresh browser (email in acme.test: sent straight to Acme).
  const alice = await (await browser.newContext()).newPage();
  await alice.goto(`${APP}/`);
  await alice.locator('#username').fill('alice@acme.test');
  await alice.locator('#kc-login').click();
  await alice.waitForURL(/realms\/acme\//, { timeout: 15000 }).catch(() => undefined);
  note('email domain sends alice to her provider', alice.url().includes('/realms/acme/'), alice.url().slice(0, 80));
  if (alice.url().includes('/realms/acme/')) {
    await alice.locator('#username').fill('alice@acme.test');
    await alice.locator('#password').fill('Alice-Acme-2026!');
    await alice.locator('#kc-login').click();
  }
  await alice.getByTestId('user-menu').waitFor({ timeout: 30000 }).catch(() => undefined);
  const aliceMe = await (await alice.request.get(`${APP}/api/v1/auth/me`)).json().catch(() => ({}));
  note('alice lands in Demo Company as a requester', aliceMe.tenant?.name === 'Demo Company', `${aliceMe.user?.email} ${aliceMe.user?.user_type} ${aliceMe.tenant?.name}`);
  await alice.screenshot({ path: `${OUT}/04-alice.png` });
} catch (error) {
  note('error', false, String(error).slice(0, 500));
  await admin.screenshot({ path: `${OUT}/99-error.png`, fullPage: true }).catch(() => undefined);
} finally {
  await browser.close();
}
