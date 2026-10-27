import { readFileSync } from 'node:fs';
import { chromium } from '@playwright/test';
const [link] = readFileSync('/private/tmp/claude-501/-Users-haiderzaidi-Extravis-supportx-v2/bae26076-1f7a-4867-9937-87165ed043a6/scratchpad/kc/invite_link.txt', 'utf8').split('\n');
const b = await chromium.launch();
const p = await (await b.newContext()).newPage();
await p.goto(link);
console.log('1st page:', (await p.locator('body').innerText()).replace(/\s+/g, ' ').slice(0, 200));
const proceed = p.getByRole('link', { name: /Click here to proceed/i });
if (await proceed.count()) await proceed.click();
await p.waitForTimeout(800);
if (await p.locator('#password-new').count()) {
  await p.locator('#password-new').fill('Ina-Vitee-2026!x'); await p.locator('#password-confirm').fill('Ina-Vitee-2026!x');
  await p.locator('input[type=submit], button[type=submit]').first().click();
  await p.waitForTimeout(1500);
}
console.log('after set:', p.url().slice(0, 100), '|', (await p.locator('body').innerText()).replace(/\s+/g, ' ').slice(0, 160));
const q = await (await b.newContext()).newPage();
await q.goto(link); await q.waitForTimeout(800);
console.log('2nd use:', (await q.locator('body').innerText()).replace(/\s+/g, ' ').slice(0, 200));
await b.close();
