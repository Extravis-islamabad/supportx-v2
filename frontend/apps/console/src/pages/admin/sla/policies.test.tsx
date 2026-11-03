import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { SlaPolicy, SlaSettings } from '@supportx/api-client';

import { App } from '../../../App';
import { consoleApi, fakeSession } from '../../../test/api';

// WP-025 session 2 screens: Admin › SLA › Policies and Settings.
let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const POLICIES = '/api/v1/sla/record-types/incident/policies';
const SETTINGS = '/api/v1/sla/record-types/incident/settings';

function policy(overrides: Partial<SlaPolicy> = {}): SlaPolicy {
  return {
    id: 'pol-default',
    record_type: 'incident',
    name: 'Standard support',
    labels: {},
    description: null,
    conditions: null,
    position: 3,
    fallback: true,
    enabled: true,
    pausing: ['first_response', 'resolution'],
    targets: [
      {
        kind: 'resolution',
        priority: 'p1',
        amount: 4,
        unit: 'hours',
        source: 'around_the_clock',
        fixed_calendar_id: null,
      },
    ],
    levels: [],
    never_matches: false,
    can_manage: true,
    version: 1,
    ...overrides,
  };
}

const VIP = policy({
  id: 'pol-vip',
  name: 'Key requesters',
  fallback: false,
  position: 1,
  conditions: { field: 'priority', op: 'eq', value: 'p1' },
  targets: [],
});
const SHADOWED = policy({
  id: 'pol-late',
  name: 'Never reached',
  fallback: false,
  position: 2,
  never_matches: true,
  targets: [],
});
const SETTINGS_ROW: SlaSettings = {
  record_type: 'incident',
  warning_percent: 75,
  priority_rule: 'recalculate',
  reopen_rule: 'resume',
  version: 3,
};
const ROUTES = {
  [`GET ${POLICIES}`]: { body: [VIP, SHADOWED, policy()] },
  'GET /api/v1/sla/calendars': { body: [] },
  'GET /api/v1/incidents/list-fields': { body: [] },
  'GET /api/v1/organization/groups': {
    body: [{ id: 'g-desk', name: 'Service desk', kind: 'group' }],
  },
  [`GET ${SETTINGS}`]: { body: SETTINGS_ROW },
};

describe('Admin › SLA › Policies', () => {
  afterEach(() => {
    restore();
  });

  it('REQ-SLA-001: lists policies in order, the default last, and flags one that never applies', async () => {
    window.history.pushState({}, '', '/admin/sla');
    api({ me: ADMIN, routes: ROUTES });
    render(<App />);
    const table = await screen.findByTestId('sla-policies');
    const rows = await within(table).findAllByTestId(/^sla-policy-row-/);
    expect(rows.map((r) => r.getAttribute('data-testid'))).toEqual([
      'sla-policy-row-pol-vip',
      'sla-policy-row-pol-late',
      'sla-policy-row-pol-default',
    ]);
    expect(rows[2]?.textContent).toContain('Default');
    expect(rows[2]?.textContent).toContain('P1 – Critical: 4 Hours');
    expect(screen.getByTestId('sla-policy-never-pol-late')).toBeTruthy();
    // The default policy cannot be moved or deleted.
    expect(screen.queryByTestId('sla-policy-delete-pol-default')).toBeNull();
    expect(screen.getByTestId<HTMLButtonElement>('sla-policy-up-pol-vip').disabled).toBe(true);
    expect(document.body.textContent).not.toMatch(/around_the_clock|first_response|\bp1\b/);
  });

  it('moves a policy down with the keyboard-reachable button', async () => {
    window.history.pushState({}, '', '/admin/sla/policies');
    const fake = api({
      me: ADMIN,
      routes: { ...ROUTES, [`PUT ${POLICIES}/order`]: { body: [SHADOWED, VIP, policy()] } },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('sla-policy-down-pol-vip'));
    await waitFor(() => {
      expect(fake.find('PUT', `${POLICIES}/order`)).toHaveLength(1);
    });
    expect(fake.find('PUT', `${POLICIES}/order`)[0]?.body).toEqual({
      policy_ids: ['pol-late', 'pol-vip'],
    });
  });

  it('adds a policy with a target table by priority', async () => {
    window.history.pushState({}, '', '/admin/sla/policies');
    const fake = api({
      me: ADMIN,
      routes: { ...ROUTES, [`POST ${POLICIES}`]: { status: 201, body: VIP } },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('sla-policy-add'));
    fireEvent.change(await screen.findByTestId('sla-policy-name'), {
      target: { value: 'Key requesters' },
    });
    fireEvent.change(screen.getByTestId('sla-target-amount-resolution-p1'), {
      target: { value: '2' },
    });
    fireEvent.click(screen.getByTestId('sla-policy-save'));
    await waitFor(() => {
      expect(fake.find('POST', POLICIES)).toHaveLength(1);
    });
    const sent = fake.find('POST', POLICIES)[0];
    expect(sent?.body).toMatchObject({
      name: 'Key requesters',
      enabled: true,
      targets: [{ kind: 'resolution', priority: 'p1', amount: 2, unit: 'hours', source: 'site' }],
    });
    expect(sent?.headers.get('Idempotency-Key')).toBeTruthy();
  });
});

describe('Admin › SLA › Policies › escalation levels', () => {
  afterEach(() => {
    restore();
  });

  it('REQ-SLA-022: adds a level an hour before the due time, sent with the policy', async () => {
    window.history.pushState({}, '', '/admin/sla/policies');
    const fake = api({
      me: ADMIN,
      routes: { ...ROUTES, [`POST ${POLICIES}`]: { status: 201, body: VIP } },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('sla-policy-add'));
    fireEvent.change(await screen.findByTestId('sla-policy-name'), {
      target: { value: 'Key requesters' },
    });
    fireEvent.click(screen.getByTestId('sla-level-add-resolution'));
    const level = await screen.findByTestId('sla-level-resolution-1');
    expect(level.textContent).toContain('Level 1 · At the due time');
    fireEvent.change(screen.getByTestId('sla-level-offset-resolution-1'), {
      target: { value: '60' },
    });
    expect(level.textContent).toContain('1 business hour after the due time');
    fireEvent.click(screen.getByTestId('sla-policy-save'));
    await waitFor(() => {
      expect(fake.find('POST', POLICIES)).toHaveLength(1);
    });
    expect(fake.find('POST', POLICIES)[0]?.body).toMatchObject({
      levels: [
        {
          kind: 'resolution',
          anchor: 'due',
          offset_seconds: 3600,
          recipients: [{ kind: 'assignee', id: null }],
          notify: true,
        },
      ],
    });
  });
});

describe('Admin › SLA › Settings', () => {
  afterEach(() => {
    restore();
  });

  it('saves the warning point with the version shown', async () => {
    window.history.pushState({}, '', '/admin/sla/settings');
    const fake = api({
      me: ADMIN,
      routes: { ...ROUTES, [`PATCH ${SETTINGS}`]: { body: { ...SETTINGS_ROW, version: 4 } } },
    });
    render(<App />);
    const warning = await screen.findByTestId('sla-settings-warning');
    fireEvent.change(warning, { target: { value: '80' } });
    fireEvent.click(screen.getByTestId('sla-settings-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', SETTINGS)).toHaveLength(1);
    });
    const sent = fake.find('PATCH', SETTINGS)[0];
    expect(sent?.body).toMatchObject({ warning_percent: 80 });
    expect(sent?.headers.get('If-Match')).toBe('"3"');
  });
});
