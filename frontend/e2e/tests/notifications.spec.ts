import { expect, test, type Browser, type Page } from '@playwright/test';

import { mailTo } from '../mail';
import { USERS } from '../stack';
import { expectAccessible, signInAs } from './helpers';

/**
 * WP-023 with two browsers (REQ-INC-131, REQ-NTF-003, REQ-NTF-008):
 * - an admin assigns a new incident to the technician; the technician's bell rises without a
 *   reload, the entry opens the incident and is then read; the e-mail reaches the mail catcher
 *   in the technician's language;
 * - Admin › Notifications lists every event with its default, and is axe clean.
 * Needs the event workers (relay, consumers, fan-out) like every live journey.
 */

const LIVE = { timeout: 10_000 };

async function open(browser: Browser, user: 'tech' | 'admin', path: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, user, path);
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected', LIVE);
  return { context, page };
}

async function csrf(page: Page): Promise<string> {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as { csrf_token: string };
  return me.csrf_token;
}

async function userId(page: Page, email: string): Promise<string> {
  const found = await page.request.get('/api/v1/users', { params: { q: email } });
  const person = ((await found.json()) as { items: { id: string }[] }).items[0];
  if (person === undefined) throw new Error(`${email} not found`);
  return person.id;
}

test('an assignment reaches the technician live, in the centre and by e-mail', async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const tech = await open(browser, 'tech', '/');
  const admin = await open(browser, 'admin', '/');
  try {
    const bell = tech.page.getByTestId('notifications-bell');
    const before = Number(/(\d+)/.exec((await bell.getAttribute('aria-label')) ?? '')?.[1] ?? 0);
    const technician = await userId(admin.page, USERS.tech.email);
    const requester = await userId(admin.page, USERS.admin.email);
    const sentAt = Date.now() - 1000;
    const subject = `E2E notify ${String(Date.now()).slice(-6)}`;
    const made = await admin.page.request.post('/api/v1/incidents', {
      data: { subject, requester_id: requester, technician_id: technician },
      headers: {
        'X-CSRF-Token': await csrf(admin.page),
        'Idempotency-Key': crypto.randomUUID(),
        'X-SupportX-Client': 'console',
      },
    });
    expect(made.status(), await made.text()).toBe(201);
    const incident = (await made.json()) as { id: string; display_id: string };

    await expect(bell).toHaveAttribute(
      'aria-label',
      `Notifications, ${String(before + 1)} unread`,
      LIVE,
    );
    await bell.click();
    const drawer = tech.page.getByTestId('notifications-drawer');
    const entry = drawer.getByTestId('notification-item').filter({ hasText: subject });
    await expect(entry).toBeVisible();
    await expect(entry).toHaveAttribute('data-read', 'false');
    await expectAccessible(tech.page, 'notification centre');
    await entry.click();
    await expect(tech.page).toHaveURL(new RegExp(`/incidents/${incident.id}`));
    await expect(bell).toHaveAttribute(
      'aria-label',
      `Notifications, ${String(before)} unread`,
      LIVE,
    );

    const mail = await mailTo(USERS.tech.email, sentAt);
    expect(mail.summary.Subject).toContain(incident.display_id);
    expect(mail.html).toContain(subject);
    expect(mail.html).toContain(`/incidents/${incident.id}`);

    await admin.page.goto('/admin/notifications');
    const rules = admin.page.getByTestId('notification-rules');
    await expect(rules.getByText('Incident assigned')).toBeVisible();
    await expect(rules.getByText('New incident: acknowledgement')).toBeVisible();
    await expectAccessible(admin.page, 'Admin › Notifications');
  } finally {
    await tech.context.close();
    await admin.context.close();
  }
});
