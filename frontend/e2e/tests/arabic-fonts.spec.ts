import { expect, test, type Page } from '@playwright/test';

import { signInAs } from './helpers';

// D-137 (QA 2026-11-04, major): Arabic and Urdu text is drawn with the bundled Noto faces in
// every weight the screens use. A heading that fell back to a system font showed the final ي
// without its dots. Measured with the font the browser really used for the element (Chrome's
// CSS.getPlatformFontsForNode), not the declared family.

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
    // The description's body text, the same way.
    expectNotoForArabic(await usedFonts(page, '[data-testid="inc-description"] p'), 'body');
  } finally {
    await page.request.delete(`/api/v1/incidents/${incident.id}`, {
      headers: { 'If-Match': `"${String(incident.version)}"`, 'X-CSRF-Token': me.csrf_token },
    });
  }
});
