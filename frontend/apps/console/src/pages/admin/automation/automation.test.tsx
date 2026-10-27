import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { RoutingSettingsOut, RuleFieldOut, RuleOut } from '@supportx/api-client';
import { fakeIncidentCatalogue, fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../../App';
import { consoleApi, problem } from '../../../test/api';

// WP-029: Admin › Incidents › Business rules and Routing; the technician availability switch.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
type Routes = NonNullable<NonNullable<Parameters<typeof consoleApi>[0]>['routes']>;
const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const ANSWERED = { technician_scope: 'group', answered_at: '2026-10-27T08:00:00Z', version: 1 };

const FIELDS: RuleFieldOut[] = [
  {
    name: 'priority',
    kind: 'code',
    values: ['p1', 'p2', 'p3', 'p4'],
    settable: true,
    derived: false,
  },
  { name: 'subject', kind: 'text', values: null, settable: false, derived: false },
];
function rule(overrides: Partial<RuleOut>): RuleOut {
  return {
    id: 'r-1',
    record_type: 'incident',
    name: 'VIP first',
    description: null,
    events: ['create'],
    conditions: null,
    actions: [{ kind: 'set', field: 'priority', value: 'p1', mode: 'overwrite' }],
    stop_after: false,
    state: 'enabled',
    position: 1,
    site_id: null,
    owner_id: null,
    updated_at: '2026-10-27T08:00:00Z',
    version: 1,
    ...overrides,
  };
}
const SETTINGS: RoutingSettingsOut = {
  record_type: 'incident',
  fallback_group_id: null,
  use_category_group: true,
  version: 0,
};
const GROUPS = [
  { id: 'g-1', name: 'Service desk', disabled: false, version: 1 },
  { id: 'g-2', name: 'Network', disabled: false, version: 1 },
];

function routes(extra: Routes = {}) {
  return api({
    me: ADMIN,
    routes: {
      'GET /api/v1/access-settings': { body: ANSWERED },
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/custom-fields': { body: [] },
      'GET /api/v1/organization/groups': { body: GROUPS },
      'GET /api/v1/organization/sites': { body: [] },
      'GET /api/v1/organization/departments': { body: [] },
      'GET /api/v1/automation/fields': { body: FIELDS },
      'GET /api/v1/automation/rules': {
        body: [rule({}), rule({ id: 'r-2', name: 'Stop here', stop_after: true, position: 2 })],
      },
      'GET /api/v1/automation/routing': { body: [] },
      'GET /api/v1/automation/routing-settings': { body: SETTINGS },
      ...extra,
    },
  });
}

function open(path: string) {
  window.history.pushState({}, '', path);
  render(<App />);
}

afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
  vi.restoreAllMocks();
});

describe('Admin › Incidents › Business rules (WP-029)', () => {
  beforeEach(() => {
    setDefaultClientFactory(inertClientFactory);
  });

  it('lists rules in order with the stop marker and state (REQ-RUL-005)', async () => {
    routes();
    open('/admin/automation/business-rules');
    const table = await screen.findByTestId('rules-table');
    await within(table).findByText('VIP first');
    expect(within(table).getAllByTestId('rule-stop-marker')).toHaveLength(1);
    expect(within(screen.getByTestId('rule-row-Stop here')).getByText('Stops here')).toBeDefined();
    expect(within(table).getAllByText('On')).toHaveLength(2);
  });

  it('moving a rule down sends the new order', async () => {
    const fake = routes({ 'PUT /api/v1/automation/rules-order': { body: [] } });
    open('/admin/automation/business-rules');
    fireEvent.click(await screen.findByRole('button', { name: 'Move “VIP first” down' }));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/automation/rules-order')).toHaveLength(1);
    });
    expect(fake.find('PUT', '/api/v1/automation/rules-order')[0]?.body).toEqual({
      record_type: 'incident',
      ids: ['r-2', 'r-1'],
    });
  });

  it('saves a rule with the version it opened and shows problems in words', async () => {
    const fake = routes({
      'PATCH /api/v1/automation/rules/r-1': {
        status: 422,
        body: problem(422, 'validation_failed', {
          errors: [
            {
              field: 'body.actions.0.field',
              code: 'field_not_settable',
              message_key: 'errors.field.field_not_settable',
              params: {},
            },
          ],
        }),
      },
    });
    open('/admin/automation/business-rules');
    fireEvent.click(await screen.findByText('VIP first'));
    const name = await screen.findByTestId('rule-name');
    fireEvent.change(name, { target: { value: 'VIP first!' } });
    fireEvent.click(screen.getByTestId('rule-save'));
    const problems = await screen.findByTestId('rule-problems');
    expect(problems.textContent).not.toContain('field_not_settable');
    const sent = fake.find('PATCH', '/api/v1/automation/rules/r-1')[0];
    expect(sent?.headers.get('If-Match')).toBe('"1"');
    expect((sent?.body as { name: string }).name).toBe('VIP first!');
  });

  it('a refusal takes its message in English, Arabic (RTL) and Urdu (RTL)', async () => {
    routes();
    open('/admin/automation/business-rules');
    fireEvent.click(await screen.findByTestId('rule-add'));
    const kind = await screen.findByTestId('action-0-kind');
    fireEvent.mouseDown(kind.querySelector('.ant-select-selector') ?? kind);
    const option = await waitFor(() => {
      const found = screen
        .getAllByText('Refuse the save')
        .filter((n) => n.closest('.ant-select-item-option') !== null);
      if (found.length === 0) throw new Error('no option');
      return found[0];
    });
    if (option !== undefined) fireEvent.click(option);
    expect((await screen.findByTestId('action-0-message-en')).getAttribute('dir')).toBe('ltr');
    expect(screen.getByTestId('action-0-message-ar').getAttribute('dir')).toBe('rtl');
    expect(screen.getByTestId('action-0-message-ur').getAttribute('dir')).toBe('rtl');
  });

  it('a rule changed elsewhere appears without a refresh (§8)', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    let rules = [rule({})];
    routes({ 'GET /api/v1/automation/rules': () => ({ body: rules }) });
    open('/admin/automation/business-rules');
    await screen.findByText('VIP first');
    rules = [rule({ name: 'Renamed', version: 2 })];
    act(() => {
      realtime.publish(':broadcast', { type: 'automation.changed', ids: [] });
    });
    expect(await screen.findByText('Renamed')).toBeDefined();
  });
});

describe('Admin › Incidents › Routing (WP-029)', () => {
  it('explains there is no fallback group until one is picked, and saves a choice', async () => {
    const fake = routes({
      'PUT /api/v1/automation/routing-settings': {
        body: { ...SETTINGS, fallback_group_id: 'g-1', version: 1 },
      },
    });
    open('/admin/automation/routing');
    const fallback = await screen.findByTestId('routing-fallback');
    expect(within(fallback).getByText('No fallback group')).toBeDefined();
    fireEvent.mouseDown(fallback.querySelector('.ant-select-selector') ?? fallback);
    const option = await waitFor(() => {
      const found = screen
        .getAllByText('Service desk')
        .filter((n) => n.closest('.ant-select-item-option') !== null);
      if (found.length === 0) throw new Error('no option');
      return found[0];
    });
    if (option !== undefined) fireEvent.click(option);
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/automation/routing-settings')).toHaveLength(1);
    });
    const sent = fake.find('PUT', '/api/v1/automation/routing-settings')[0];
    expect(sent?.body).toEqual({ fallback_group_id: 'g-1' });
    expect(sent?.headers.get('If-Match')).toBe('"0"');
  });
});

describe('Availability switch (WP-029, REQ-ASG-006)', () => {
  it('a technician sets themselves Away on My profile', async () => {
    const fake = routes({
      'PUT /api/v1/automation/availability/01900000-0000-7000-8000-000000000101': {
        body: { user_id: '01900000-0000-7000-8000-000000000101', state: 'away' },
      },
    });
    open('/profile');
    const toggle = await screen.findByTestId('availability-profile-switch');
    // A loading switch ignores clicks: wait for the current state first.
    await waitFor(() => {
      expect(toggle.className).not.toContain('ant-switch-loading');
    });
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    fireEvent.click(toggle);
    await waitFor(() => {
      expect(
        fake.find('PUT', '/api/v1/automation/availability/01900000-0000-7000-8000-000000000101'),
      ).toHaveLength(1);
    });
    expect(
      fake.find('PUT', '/api/v1/automation/availability/01900000-0000-7000-8000-000000000101')[0]
        ?.body,
    ).toEqual({ state: 'away' });
  });
});
