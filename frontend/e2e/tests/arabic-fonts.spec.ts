import { expect, test, type Page } from '@playwright/test';

import { signInAs } from './helpers';

// D-137 (QA 2026-11-04, major): the record title's final ي lost its dots. Not the font: the
// two-line clamp (overflow hidden, line height 1.3) cut off the dots below Arabic letters. A
// clamped title with Arabic-script text gets the script's line height (1.7 Naskh, 1.9
// Nastaliq). Checked here in English, Arabic and Urdu (Nastaliq), with the font Chrome really
// used (CSS.getPlatformFontsForNode). Ink below the line box is not scrollable overflow, so the
// line height is what is measured, not scrollHeight.

const ARABIC = 'الشبكة بطيئة جدًا في مكتب دبي';

/**
 * The platform fonts Chrome used for the text directly inside the first match, with how many
 * glyphs each drew. Platform names carry the weight ("Noto Sans Arabic SemiBold").
 */
async function usedFonts(page: Page, selector: string): Promise<Record<string, number>> {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('DOM.enable');
  await cdp.send('CSS.enable');
  const { root } = await cdp.send('DOM.getDocument', { depth: -1 });
  const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector });
  expect(nodeId, selector).toBeGreaterThan(0);
  const { fonts } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId });
  return Object.fromEntries(fonts.map((f) => [f.familyName, f.glyphCount]));
}

async function prefer(page: Page, values: Record<string, string | null>): Promise<void> {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
    csrf_token: string;
    user: { id: string };
  };
  const path = `/api/v1/users/${me.user.id}`;
  const current = (await (await page.request.get(path)).json()) as { version: number };
  const saved = await page.request.patch(path, {
    data: values,
    headers: { 'If-Match': `"${String(current.version)}"`, 'X-CSRF-Token': me.csrf_token },
  });
  expect(saved.status(), await saved.text()).toBe(200);
}

/** Arabic letters drawn by Noto Sans Arabic (any weight); only spaces and Latin by Inter. */
function expectNotoForArabic(fonts: Record<string, number>, where: string): void {
  const names = Object.keys(fonts);
  expect(
    names.some((n) => n.startsWith('Noto Sans Arabic')),
    `${where}: ${JSON.stringify(fonts)}`,
  ).toBe(true);
  expect(
    names.filter((n) => !n.startsWith('Noto Sans Arabic') && !n.startsWith('Inter')),
    `${where}: no other font draws it (${JSON.stringify(fonts)})`,
  ).toEqual([]);
}

test('Arabic in headings and body uses the bundled Noto Sans Arabic in every weight', async ({
  page,
}) => {
  await signInAs(page, 'tech', '/incidents');
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
    csrf_token: string;
    user: { id: string };
  };
  const made = await page.request.post('/api/v1/incidents', {
    data: { subject: ARABIC, requester_id: me.user.id, description: `<p>${ARABIC}</p>` },
    headers: { 'X-CSRF-Token': me.csrf_token },
  });
  expect(made.status(), await made.text()).toBe(201);
  const incident = (await made.json()) as { id: string; version: number };
  try {
    await page.goto(`/incidents/${incident.id}`);
    const title = page.getByTestId('inc-heading');
    await expect(title).toContainText('مكتب');
    // Every weight the screens use has its own Arabic face (none is faked from another).
    const weights = await page.evaluate(async () => {
      await document.fonts.ready;
      return [...document.fonts]
        .filter((f) => f.family.replaceAll(/["']/g, '') === 'Noto Sans Arabic')
        .map((f) => f.weight)
        .sort();
    });
    expect(weights, 'Noto Sans Arabic faces declared').toEqual(['400', '500', '600', '700']);
    expectNotoForArabic(await usedFonts(page, '[data-testid="inc-heading"] bdi'), 'heading');
    const weight = await title.evaluate((el) => getComputedStyle(el).fontWeight);
    test.info().annotations.push({ type: 'heading weight', description: weight });
    // Room below the letters for their dots, in every language and Urdu style.
    const ratio = () =>
      title.evaluate((el) => {
        const style = getComputedStyle(el);
        return parseFloat(style.lineHeight) / parseFloat(style.fontSize);
      });
    expect(await ratio(), 'English UI').toBeGreaterThanOrEqual(1.65);
    for (const [ui_locale, urdu_script, least] of [
      ['ar', null, 1.65],
      ['ur', 'nastaliq', 1.85],
    ] as const) {
      await prefer(page, { ui_locale, urdu_script });
      await page.reload();
      await expect(title).toContainText('مكتب');
      expect(await ratio(), `${ui_locale} ${String(urdu_script)}`).toBeGreaterThanOrEqual(least);
    }
    await prefer(page, { ui_locale: null, urdu_script: null });
    await page.reload();
    // The description's body text, the same way.
    expectNotoForArabic(await usedFonts(page, '[data-testid="inc-description"] p'), 'body');
  } finally {
    await page.request.delete(`/api/v1/incidents/${incident.id}`, {
      headers: { 'If-Match': `"${String(incident.version)}"`, 'X-CSRF-Token': me.csrf_token },
    });
  }
});
