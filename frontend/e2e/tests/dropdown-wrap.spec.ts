import { expect, test, type Page } from '@playwright/test';

import { PORTAL_URL, USERS, passwordOf } from '../stack';
import { resetLanguage, signIn, signInAs } from './helpers';

/**
 * Dropdown options never break inside a word (product owner, 2026-10-28: "tab / le / sta / ck").
 * Every Select on the main console and portal screens is opened, in English, Arabic and Urdu, at
 * desktop width and at 390 px. Per option:
 * - no word's letters land on two lines (each word measured with a DOM Range);
 * - the list stays on the screen and is at least as wide as its field;
 * - an option cut short (a single word too long) carries its full text as a tooltip (title).
 */

const CONSOLE_PAGES = [
  '/',
  '/dashboards/builtin%3Aservice_desk',
  '/dashboards/builtin%3Amy_work',
  '/incidents',
  '/reports',
  '/admin/incidents/settings',
  '/admin/users',
];
const LOCALES = ['en', 'ar', 'ur'] as const;
const WIDTHS = [
  { name: 'desktop', width: 1280, height: 800 },
  { name: '390 px', width: 390, height: 844 },
] as const;

interface Problem {
  option: string;
  problem: string;
}

/** Problems of the dropdown list now open on `page` (empty when it is right). */
async function listProblems(
  page: Page,
  field: { left: number; width: number },
): Promise<Problem[]> {
  return page.evaluate((fieldBox) => {
    const found: { option: string; problem: string }[] = [];
    const popup = [...document.querySelectorAll<HTMLElement>('.ant-select-dropdown')].find(
      (p) => p.offsetParent !== null && !p.className.includes('-leave'),
    );
    if (popup === undefined) return found;
    const box = popup.getBoundingClientRect();
    if (box.left < -1 || box.right > window.innerWidth + 1) {
      found.push({
        option: '(list)',
        problem: `off screen: ${String(box.left)}..${String(box.right)}`,
      });
    }
    if (box.width + 1 < Math.min(fieldBox.width, window.innerWidth - 16)) {
      found.push({ option: '(list)', problem: `narrower than its field: ${String(box.width)}` });
    }
    for (const content of popup.querySelectorAll<HTMLElement>('.ant-select-item-option-content')) {
      const text = content.textContent;
      const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
        const value = node.textContent ?? '';
        for (const word of value.matchAll(/\S+/g)) {
          const range = document.createRange();
          range.setStart(node, word.index);
          range.setEnd(node, word.index + word[0].length);
          const tops = new Set([...range.getClientRects()].map((r) => Math.round(r.top)));
          if (tops.size > 1) found.push({ option: text, problem: `"${word[0]}" breaks inside` });
        }
      }
      const option = content.closest<HTMLElement>('.ant-select-item-option');
      if (content.scrollWidth > content.clientWidth + 1 && option?.title !== text) {
        found.push({ option: text, problem: 'cut short without its full text as a tooltip' });
      }
    }
    return found;
  }, field);
}

/** Open every enabled Select on the page in turn; the problems found, by field. */
async function pageProblems(page: Page, where: string): Promise<string[]> {
  const problems: string[] = [];
  const selects = page.locator('main .ant-select:not(.ant-select-disabled)');
  const count = Math.min(await selects.count(), 12);
  for (let index = 0; index < count; index += 1) {
    const select = selects.nth(index);
    if (!(await select.isVisible())) continue;
    await select.scrollIntoViewIfNeeded();
    const field = await select.boundingBox();
    if (field === null) continue;
    await select.click();
    const popup = page.locator('.ant-select-dropdown:visible:not([class*="-leave"])').last();
    if (!(await popup.isVisible().catch(() => false))) {
      await page.keyboard.press('Escape');
      continue;
    }
    await expect(popup).not.toHaveClass(/ant-slide-up-(appear|enter)/);
    for (const p of await listProblems(page, { left: field.x, width: field.width })) {
      problems.push(`${where} · field ${String(index + 1)} · ${p.option}: ${p.problem}`);
    }
    await page.keyboard.press('Escape');
    await expect(popup).toBeHidden();
  }
  return problems;
}

async function setLanguage(page: Page, locale: (typeof LOCALES)[number]): Promise<void> {
  const request = page.context().request;
  const me = (await (await request.get('/api/v1/auth/me')).json()) as {
    csrf_token: string;
    user: { id: string };
  };
  const path = `/api/v1/users/${me.user.id}`;
  const user = (await (await request.get(path)).json()) as { version: number };
  const saved = await request.patch(path, {
    data: { ui_locale: locale === 'en' ? null : locale },
    headers: { 'If-Match': `"${String(user.version)}"`, 'X-CSRF-Token': me.csrf_token },
  });
  expect(saved.status(), await saved.text()).toBe(200);
}

for (const size of WIDTHS) {
  test(`console dropdowns wrap only between words (${size.name}, en/ar/ur)`, async ({ page }) => {
    test.setTimeout(600_000);
    await page.setViewportSize({ width: size.width, height: size.height });
    await signInAs(page, 'admin', '/');
    const problems: string[] = [];
    try {
      for (const locale of LOCALES) {
        await setLanguage(page, locale);
        for (const path of CONSOLE_PAGES) {
          await page.goto(path);
          await expect(page.locator('html')).toHaveAttribute('lang', locale);
          await page.locator('main').waitFor();
          await page.waitForLoadState('networkidle').catch(() => undefined);
          problems.push(...(await pageProblems(page, `${locale} ${path}`)));
        }
      }
    } finally {
      await resetLanguage(page);
    }
    expect(problems).toEqual([]);
  });
}

test('portal dropdowns wrap only between words (desktop and 390 px, en/ar/ur)', async ({
  page,
}) => {
  test.setTimeout(300_000);
  await signIn(page, USERS.limited.email, passwordOf('limited'), `${PORTAL_URL}/`);
  const problems: string[] = [];
  try {
    for (const size of WIDTHS) {
      await page.setViewportSize({ width: size.width, height: size.height });
      for (const locale of LOCALES) {
        await setLanguage(page, locale);
        for (const path of ['/', '/account']) {
          await page.goto(`${PORTAL_URL}${path}`);
          await expect(page.locator('html')).toHaveAttribute('lang', locale);
          await page.waitForLoadState('networkidle').catch(() => undefined);
          problems.push(...(await pageProblems(page, `portal ${size.name} ${locale} ${path}`)));
        }
      }
    }
  } finally {
    await resetLanguage(page);
  }
  expect(problems).toEqual([]);
});
