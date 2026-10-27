import { chromium } from '@playwright/test';
const b = await chromium.launch(); const p = await (await b.newContext()).newPage();
await p.goto('http://localhost:5183/');
await p.locator('#username').fill('alice@acme.test'); await p.locator('#kc-login').click();
await p.waitForTimeout(3000); console.log('after email:', p.url().slice(0, 100));
await b.close();
