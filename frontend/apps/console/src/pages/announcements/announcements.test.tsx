import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { fakeAnnouncement } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi, fakeSession, problem } from '../../test/api';

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const ITEM = fakeAnnouncement();
const PATH = `/api/v1/announcements/${ITEM.id}`;

describe('Announcements list', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/announcements');
  });
  afterEach(() => {
    restore();
  });

  it('lists with labels (never codes) and filters with the DSL', async () => {
    const fake = api({
      me: ADMIN,
      routes: {
        'GET /api/v1/announcements': {
          body: {
            items: [
              {
                ...ITEM,
                status: 'published',
                visibility: 'scheduled',
                deleted_at: null,
              },
            ],
            has_more: false,
            next_cursor: null,
            next_change_in_seconds: 120,
          },
        },
        'GET /api/v1/announcements/settings': {
          body: { require_second_publisher: false, version: 0 },
        },
      },
    });
    render(<App />);
    const row = await screen.findByTestId('ann-row-ANN-1');
    expect(within(row).getByText('Published')).toBeDefined();
    expect(within(row).getByText('Scheduled')).toBeDefined();
    expect(within(row).getByText('Warning')).toBeDefined();
    expect(row.textContent).not.toMatch(/scheduled|warning|everyone/);
    // Admins see the four-eyes switch.
    expect(await screen.findByTestId('ann-four-eyes')).toBeDefined();

    fireEvent.change(screen.getByRole('searchbox', { name: 'Search titles' }), {
      target: { value: 'mail' },
    });
    await waitFor(() => {
      const last = fake.find('GET', '/api/v1/announcements').at(-1);
      expect(JSON.parse(last?.url.searchParams.get('filter') ?? 'null')).toEqual({
        field: 'title',
        op: 'contains',
        value: 'mail',
      });
    });
    // Every call says which app it came from and the user's time zone.
    const call = fake.find('GET', '/api/v1/announcements')[0];
    expect(call?.headers.get('X-SupportX-Client')).toBe('console');
    expect(call?.headers.get('X-Time-Zone')).toBeTruthy();
  });
});

describe('One announcement', () => {
  beforeEach(() => {
    window.history.pushState({}, '', `/announcements/${ITEM.id}`);
  });
  afterEach(() => {
    restore();
  });

  it('shows every action in a fixed order; disabled ones say why', async () => {
    api({
      routes: {
        [`GET ${PATH}`]: {
          body: fakeAnnouncement({
            actions: [
              { action: 'publish', allowed: false, reason: 'four_eyes' },
              { action: 'unpublish', allowed: false, reason: 'not_from_status' },
              { action: 'archive', allowed: true, reason: null },
              { action: 'reopen', allowed: false, reason: 'not_from_status' },
            ],
          }),
          headers: { ETag: '"1"' },
        },
        [`GET ${PATH}/history`]: { body: { items: [], next_cursor: null } },
      },
    });
    render(<App />);
    const actions = await screen.findByTestId('ann-actions');
    const buttons = within(actions).getAllByRole('button');
    expect(buttons.map((b) => b.textContent)).toEqual([
      'Publish',
      'Unpublish',
      'Archive',
      'Reopen',
    ]);
    expect((buttons[0] as HTMLButtonElement).disabled).toBe(true);
    expect((buttons[2] as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByTestId('ann-action-publish-reason').getAttribute('data-reason')).toBe(
      'four_eyes',
    );
    fireEvent.mouseOver(screen.getByTestId('ann-action-publish-reason'));
    expect(
      await screen.findByText('Someone other than the author or owner must publish it.'),
    ).toBeDefined();
  });

  it('archive asks for an optional reason and sends it with If-Match', async () => {
    const fake = api({
      me: ADMIN,
      routes: {
        [`GET ${PATH}`]: { body: ITEM, headers: { ETag: '"1"' } },
        [`GET ${PATH}/history`]: { body: { items: [], next_cursor: null } },
        [`POST ${PATH}/archive`]: {
          body: fakeAnnouncement({ status: 'archived', version: 2 }),
          headers: { ETag: '"2"' },
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('ann-action-archive'));
    fireEvent.change(await screen.findByTestId('ann-reason'), {
      target: { value: 'Duplicate' },
    });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Archive' }));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/archive`)).toHaveLength(1);
    });
    const call = fake.find('POST', `${PATH}/archive`)[0];
    expect(call?.headers.get('If-Match')).toBe('"1"');
    expect(call?.body).toEqual({ reason: 'Duplicate' });
  });

  it('a 409 on save says who changed which fields', async () => {
    api({
      me: ADMIN,
      routes: {
        [`GET ${PATH}`]: { body: ITEM, headers: { ETag: '"1"' } },
        [`GET ${PATH}/history`]: { body: { items: [], next_cursor: null } },
        [`PATCH ${PATH}`]: {
          status: 409,
          body: problem(409, 'version_conflict', {
            params: {
              expected_version: 1,
              current_version: 2,
              changed_by: 'Aisha Tech',
              changed_fields: 'title',
              changed_at: '2026-10-23T10:15:00Z',
            },
          }),
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('ann-edit'));
    fireEvent.change(await screen.findByTestId('ann-title'), { target: { value: 'New title' } });
    fireEvent.click(screen.getByTestId('ann-save'));
    const who = await screen.findByTestId('conflict-who');
    expect(who.textContent).toContain('Aisha Tech saved it at');
    expect(who.textContent).toContain('Changed: Title.');
  });

  it('an announcement that does not exist (or is not yours to see) is a clear not-found', async () => {
    api({
      routes: {
        [`GET ${PATH}`]: { status: 404, body: problem(404, 'announcement_not_found') },
      },
    });
    render(<App />);
    expect(
      await screen.findByText('This announcement does not exist or is not available to you.'),
    ).toBeDefined();
  });
});
