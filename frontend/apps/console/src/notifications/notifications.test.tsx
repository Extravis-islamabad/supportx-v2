import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeNotification, fakeNotificationRule, fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../App';
import { consoleApi } from '../test/api';

// WP-023: the notification centre (REQ-INC-131), preferences (REQ-NTF-016), the rules screen
// (REQ-NTF-008) and the admins' mail-waiting banner (REQ-NTF-020 AC3).

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });

afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

describe('the notification centre', () => {
  it('REQ-INC-131 AC1, AC2: a new entry raises the badge live; opening it opens the record and marks it read', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    let entries = [] as ReturnType<typeof fakeNotification>[];
    const fake = api({
      routes: {
        'GET /api/v1/notifications': () => ({
          body: {
            items: entries,
            next_cursor: null,
            unread: entries.filter((e) => !e.read).length,
          },
        }),
        'POST /api/v1/notifications/read': () => {
          entries = entries.map((e) => ({ ...e, read: true }));
          return { body: { changed: 1, unread: 0 } };
        },
      },
    });
    window.history.pushState({}, '', '/');
    render(<App />);
    const bell = await screen.findByTestId('notifications-bell');
    expect(bell.getAttribute('aria-label')).toBe('Notifications, 0 unread');
    entries = [fakeNotification()];
    act(() => {
      realtime.publish(':user:01900000-0000-7000-8000-000000000101', {
        type: 'notifications.created',
        ids: [entries[0]?.id ?? ''],
      });
    });
    await waitFor(() => {
      expect(screen.getByTestId('notifications-bell').getAttribute('aria-label')).toBe(
        'Notifications, 1 unread',
      );
    });
    fireEvent.click(screen.getByTestId('notifications-bell'));
    const drawer = await screen.findByTestId('notifications-drawer');
    const item = await within(drawer).findByTestId('notification-item');
    expect(item.getAttribute('data-read')).toBe('false');
    expect(within(item).getByText(/INC-12 is assigned/)).toBeTruthy();
    fireEvent.click(item);
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/notifications/read')).toHaveLength(1);
    });
    expect(fake.find('POST', '/api/v1/notifications/read')[0]?.body).toEqual({
      ids: [entries[0]?.id],
    });
    await waitFor(() => {
      expect(window.location.pathname).toBe('/incidents/01900000-0000-7000-8000-0000000001c1');
    });
  });

  it('marks everything read at once and says when there is nothing', async () => {
    const fake = api({
      routes: {
        'GET /api/v1/notifications': {
          body: {
            items: [
              fakeNotification(),
              fakeNotification({ id: '01900000-0000-7000-8000-00000000a002' }),
            ],
            next_cursor: null,
            unread: 2,
          },
        },
        'POST /api/v1/notifications/read': { body: { changed: 2, unread: 0 } },
      },
    });
    window.history.pushState({}, '', '/');
    render(<App />);
    fireEvent.click(await screen.findByTestId('notifications-bell'));
    fireEvent.click(await screen.findByTestId('notifications-read-all'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/notifications/read')[0]?.body).toEqual({});
    });
  });
});

describe('preferences on My profile', () => {
  it('REQ-NTF-016 AC2: required kinds are locked; a change saves with If-Match', async () => {
    const choices = [
      { category: 'mention', channel: 'in_app', on: true, locked: true },
      { category: 'mention', channel: 'email', on: true, locked: true },
      { category: 'conversation', channel: 'in_app', on: true, locked: false },
      { category: 'conversation', channel: 'email', on: true, locked: false },
    ] as const;
    const fake = api({
      routes: {
        'GET /api/v1/notifications/preferences': {
          body: { choices, do_not_disturb: false, version: 3 },
        },
        'PUT /api/v1/notifications/preferences': {
          body: { choices, do_not_disturb: false, version: 4 },
        },
      },
    });
    window.history.pushState({}, '', '/profile');
    render(<App />);
    const card = await screen.findByTestId('notification-preferences');
    const locked = await within(card).findByTestId('pref-mention-email');
    expect(locked.closest('label')?.querySelector('input')?.disabled).toBe(true);
    const email = within(card).getByTestId('pref-conversation-email');
    fireEvent.click(email.closest('label')?.querySelector('input') ?? email);
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/notifications/preferences')).toHaveLength(1);
    });
    const [saved] = fake.find('PUT', '/api/v1/notifications/preferences');
    expect(saved?.headers.get('If-Match')).toBe('"3"');
    expect(saved?.body).toEqual({
      off: [{ category: 'conversation', channel: 'email' }],
      do_not_disturb: false,
    });
  });
});

describe('Admin › Notifications', () => {
  it('REQ-NTF-008 AC1: every event with its default; switching one off saves its version', async () => {
    const created = fakeNotificationRule();
    const assigned = fakeNotificationRule({
      event_code: 'incident.assigned',
      category: 'assignment',
      required: true,
      recipients: ['assignee'],
      default_recipients: ['assignee'],
    });
    const fake = api({
      me: ADMIN,
      routes: {
        'GET /api/v1/notifications/rules': { body: [created, assigned] },
        'PUT /api/v1/notifications/rules/incident.created': {
          body: { ...created, enabled: false, is_default: false, version: 1 },
        },
      },
    });
    window.history.pushState({}, '', '/admin/notifications');
    render(<App />);
    const table = await screen.findByTestId('notification-rules');
    expect(await within(table).findByText('New incident: acknowledgement')).toBeTruthy();
    expect(within(table).getByText('Incident assigned')).toBeTruthy();
    expect(within(table).getByText('Required for people')).toBeTruthy();
    expect(within(table).getAllByText('Default')).toHaveLength(2);
    fireEvent.click(within(table).getByTestId('rule-on-incident.created'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/notifications/rules/incident.created')).toHaveLength(1);
    });
    const [saved] = fake.find('PUT', '/api/v1/notifications/rules/incident.created');
    expect(saved?.headers.get('If-Match')).toBe('"0"');
    expect(saved?.body).toMatchObject({ enabled: false, recipients: ['requester'] });
  });

  it('REQ-NTF-020 AC3: admins see how many e-mails wait for outgoing mail', async () => {
    api({
      me: ADMIN,
      routes: {
        'GET /api/v1/notifications/status': { body: { mail_configured: false, waiting: 7 } },
      },
    });
    window.history.pushState({}, '', '/');
    render(<App />);
    const banner = await screen.findByTestId('notifications-banner');
    expect(banner.textContent).toContain('7 e-mails wait because outgoing mail is not set up');
  });

  it('technicians see no banner and no rules tab', async () => {
    api({
      routes: {
        'GET /api/v1/notifications/status': { body: { mail_configured: false, waiting: 7 } },
      },
    });
    window.history.pushState({}, '', '/');
    render(<App />);
    await screen.findByTestId('notifications-bell');
    expect(screen.queryByTestId('notifications-banner')).toBeNull();
  });
});
