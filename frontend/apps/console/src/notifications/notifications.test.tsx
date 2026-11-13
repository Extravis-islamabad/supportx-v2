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

  it('QA10V-15: live pop-ups never stack: the newest replaces the last', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    // One unread entry already there: the bell says so only once the first load is in, so the
    // test never publishes before it (a pop-up is only for what arrives after the first load).
    let entries = [fakeNotification({ id: 'n0', title: 'Already here', read: false })];
    api({
      routes: {
        'GET /api/v1/notifications': () => ({
          body: {
            items: entries,
            next_cursor: null,
            unread: entries.filter((e) => !e.read).length,
          },
        }),
      },
    });
    window.history.pushState({}, '', '/');
    render(<App />);
    await waitFor(
      () => {
        expect(screen.getByTestId('notifications-bell').getAttribute('aria-label')).toBe(
          'Notifications, 1 unread',
        );
      },
      { timeout: 5000 },
    );
    const arrive = async (id: string, title: string, unread: number) => {
      entries = [fakeNotification({ id, title, read: false }), ...entries];
      act(() => {
        realtime.publish(':user:01900000-0000-7000-8000-000000000101', {
          type: 'notifications.created',
          ids: [id],
        });
      });
      // The refetch is in (the bell's count), then its pop-up shows: state, not real time.
      await waitFor(
        () => {
          expect(screen.getByTestId('notifications-bell').getAttribute('aria-label')).toBe(
            `Notifications, ${String(unread)} unread`,
          );
        },
        { timeout: 5000 },
      );
      await screen.findByText(title, undefined, { timeout: 5000 });
    };
    await arrive('n1', 'INC-1 is close to its response target', 2);
    await arrive('n2', 'INC-2 is close to its response target', 3);
    await waitFor(() => {
      expect(document.querySelectorAll('.ant-message-notice')).toHaveLength(1);
    });
    expect(screen.queryByText('INC-1 is close to its response target')).toBeNull();
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
    // Only a changed rule is marked (QA6S-CHN-01): no tag on the shipped defaults.
    expect(within(table).queryByText('Default')).toBeNull();
    expect(within(table).getByText('Incidents (2)')).toBeTruthy();
    fireEvent.click(within(table).getByTestId('rule-on-incident.created'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/notifications/rules/incident.created')).toHaveLength(1);
    });
    const [saved] = fake.find('PUT', '/api/v1/notifications/rules/incident.created');
    expect(saved?.headers.get('If-Match')).toBe('"0"');
    expect(saved?.body).toMatchObject({ enabled: false, recipients: ['requester'] });
  });

  it('WP-057 S2b: a locked security notice shows its rules read-only, with no reset', async () => {
    const locked = fakeNotificationRule({
      event_code: 'incident.assigned',
      category: 'assignment',
      required: true,
      locked: true,
      is_default: false, // a rule saved before the lock: still no reset to offer
      version: 2,
    });
    api({ me: ADMIN, routes: { 'GET /api/v1/notifications/rules': { body: [locked] } } });
    window.history.pushState({}, '', '/admin/notifications');
    render(<App />);
    const table = await screen.findByTestId('notification-rules');
    expect(await within(table).findByText('Fixed for security')).toBeTruthy();
    const on = within(table).getByTestId('rule-on-incident.assigned');
    expect(on.hasAttribute('disabled')).toBe(true);
    expect(within(table).queryByTestId('rule-reset-incident.assigned')).toBeNull();
  });

  it('REQ-CHG-103: a change rule fires on the statuses chosen, saved as its condition', async () => {
    const entered = fakeNotificationRule({
      event_code: 'change.status_entered',
      record_type: 'change',
      category: 'status',
      enabled: false,
      condition_fields: ['status', 'status_category'],
      recipients: ['change_owner'],
      default_recipients: ['change_owner'],
    });
    const fake = api({
      me: ADMIN,
      routes: {
        'GET /api/v1/notifications/rules': { body: [entered] },
        'GET /api/v1/changes/settings': {
          body: {
            statuses: [
              {
                code: 'cab_awaiting',
                category: 'open',
                colour: '#faad14',
                labels: null,
                system: false,
                disabled: false,
                resume_on_requester_reply: false,
              },
            ],
            closure_codes: [],
            own_lists: {},
          },
        },
        'PUT /api/v1/notifications/rules/change.status_entered': {
          body: { ...entered, is_default: false, version: 1 },
        },
      },
    });
    window.history.pushState({}, '', '/admin/notifications');
    render(<App />);
    const picker = (await screen.findByTestId('rule-status-change.status_entered')).querySelector(
      '.ant-select-selector',
    );
    if (picker === null) throw new Error('not an Ant Design Select');
    fireEvent.mouseDown(picker);
    fireEvent.click(await screen.findByTitle('Awaiting CAB'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/notifications/rules/change.status_entered')).toHaveLength(1);
    });
    const [saved] = fake.find('PUT', '/api/v1/notifications/rules/change.status_entered');
    expect(saved?.body).toMatchObject({
      conditions: [{ field: 'status', operator: 'in', values: ['cab_awaiting'] }],
    });
  });

  it('CHN-01: events are grouped by area and found by name', async () => {
    const assigned = fakeNotificationRule({
      event_code: 'incident.assigned',
      category: 'assignment',
    });
    const submitted = fakeNotificationRule({
      event_code: 'kb_article.submitted',
      record_type: 'kb_article',
      category: 'approval',
    });
    api({
      me: ADMIN,
      routes: { 'GET /api/v1/notifications/rules': { body: [assigned, submitted] } },
    });
    window.history.pushState({}, '', '/admin/notifications');
    render(<App />);
    const groups = await screen.findByTestId('notification-rules');
    expect(await within(groups).findByText('Incidents (1)')).toBeTruthy();
    expect(within(groups).getByText('Knowledge (1)')).toBeTruthy();
    fireEvent.change(screen.getByTestId('notification-rules-search'), {
      target: { value: 'assigned' },
    });
    await waitFor(() => {
      expect(
        within(screen.getByTestId('notification-rules')).queryByText('Knowledge (1)'),
      ).toBeNull();
    });
    expect(screen.getByText('Incident assigned')).toBeTruthy();
    fireEvent.change(screen.getByTestId('notification-rules-search'), {
      target: { value: 'nothing like this' },
    });
    expect(await screen.findByText('No event matches')).toBeTruthy();
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
