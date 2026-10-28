import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AutomationRunOut, Incident, TriggerOut } from '@supportx/api-client';
import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
  fakeSession,
} from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';
import { rememberTab } from '../../incidents/tabs';

// WP-029 part 2: triggers, transition settings, the record's automation panel, loop warnings.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
type Routes = NonNullable<NonNullable<Parameters<typeof consoleApi>[0]>['routes']>;
const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const ANSWERED = { technician_scope: 'group', answered_at: '2026-10-27T08:00:00Z', version: 1 };
const ITEM = fakeIncident();
const PATH = `/api/v1/incidents/${ITEM.id}`;

function trigger(overrides: Partial<TriggerOut>): TriggerOut {
  return {
    id: 't-1',
    record_type: 'incident',
    name: 'Resolved check',
    description: null,
    events: ['status_changed'],
    site_id: null,
    conditions: { field: 'status', op: 'changed_to', value: 'resolved' },
    actions: [{ kind: 'note', text: 'Check with the user.', mode: 'fill_empty' }],
    fire_on_own_change: false,
    position: 1,
    state: 'enabled',
    owner_id: null,
    updated_at: '2026-10-27T08:00:00Z',
    version: 1,
    ...overrides,
  };
}

function run(overrides: Partial<AutomationRunOut>): AutomationRunOut {
  return {
    id: 'run-1',
    kind: 'trigger',
    automation_name: 'Two steps',
    outcome: 'partial',
    detail: {
      actions: [
        { kind: 'set', field: 'group_id', outcome: 'failed', reason: 'group_not_found' },
        { kind: 'note', field: null, outcome: 'applied' },
      ],
    },
    occurred_at: new Date().toISOString(),
    ...overrides,
  };
}

function routes(extra: Routes = {}) {
  return api({
    me: ADMIN,
    routes: {
      'GET /api/v1/access-settings': { body: ANSWERED },
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
      'GET /api/v1/incidents/categories': { body: [] },
      'GET /api/v1/custom-fields': { body: [] },
      'GET /api/v1/roles': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/organization/sites': { body: [] },
      'GET /api/v1/organization/departments': { body: [] },
      'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
      'GET /api/v1/automation/fields': {
        body: [
          {
            name: 'status',
            kind: 'code',
            values: ['new', 'resolved'],
            settable: false,
            derived: false,
          },
          { name: 'priority', kind: 'code', values: ['p1', 'p2'], settable: true, derived: false },
        ],
      },
      'GET /api/v1/automation/triggers': { body: [trigger({})] },
      'GET /api/v1/automation/transitions': { body: [] },
      [`GET ${PATH}`]: { body: ITEM, headers: { ETag: `"${String(ITEM.version)}"` } },
      [`GET ${PATH}/history`]: { body: { items: [], next_cursor: null, people: {} } },
      [`GET ${PATH}/automation`]: { body: [] },
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

describe('Admin › Incidents › Triggers (WP-029 part 2)', () => {
  beforeEach(() => {
    setDefaultClientFactory(inertClientFactory);
  });

  it('lists triggers with their events and state (REQ-RUL-009)', async () => {
    routes();
    open('/admin/automation/triggers');
    const row = await screen.findByTestId('trigger-row-Resolved check');
    expect(within(row).getByText('When the status changes')).toBeDefined();
    expect(within(row).getByText('On')).toBeDefined();
  });

  it('a new trigger offers "changed from" for the status only', async () => {
    routes();
    open('/admin/automation/triggers');
    fireEvent.click(await screen.findByTestId('trigger-add'));
    fireEvent.click(await screen.findByTestId('condition-add'));
    const pickField = async (label: string) => {
      const select = await screen.findByTestId('condition-0-field');
      fireEvent.mouseDown(select.querySelector('.ant-select-selector') ?? select);
      const option = await waitFor(() => {
        const found = screen
          .getAllByText(label)
          .filter((n) => n.closest('.ant-select-item-option') !== null);
        const last = found[found.length - 1];
        if (last === undefined) throw new Error('no option');
        return last;
      });
      fireEvent.click(option);
    };
    const operators = async () => {
      const select = screen.getByTestId('condition-0-op');
      fireEvent.mouseDown(select.querySelector('.ant-select-selector') ?? select);
      await screen.findAllByText('changed to');
      return screen
        .queryAllByText('changed from')
        .filter((n) => n.closest('.ant-select-item-option') !== null).length;
    };
    await pickField('Priority');
    expect(await operators()).toBe(0);
  });

  it('a trigger changed elsewhere appears without a refresh (§8)', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    let triggers = [trigger({})];
    routes({ 'GET /api/v1/automation/triggers': () => ({ body: triggers }) });
    open('/admin/automation/triggers');
    await screen.findByText('Resolved check');
    triggers = [trigger({ name: 'Renamed', version: 2 })];
    act(() => {
      realtime.publish(':broadcast', { type: 'automation.changed', ids: [] });
    });
    expect(await screen.findByText('Renamed')).toBeDefined();
  });
});

describe('Admin › Incidents › Transitions (REQ-WF-003, 004)', () => {
  it('limits "Resolve" to the assignee, saving with If-Match "0" the first time', async () => {
    const fake = routes({
      'PUT /api/v1/automation/transitions/resolve': {
        body: {
          record_type: 'incident',
          action: 'resolve',
          roles: [],
          group_ids: [],
          relatives: ['assignee'],
          conditions: null,
          confirmation: null,
          after_actions: [],
          version: 1,
        },
      },
    });
    open('/admin/automation/transitions');
    expect((await screen.findByTestId('transition-summary-resolve')).textContent).toBe(
      'Everyone with the permission',
    );
    fireEvent.click(screen.getByTestId('transition-edit-resolve'));
    fireEvent.click(await screen.findByText('The assigned technician'));
    fireEvent.click(screen.getByTestId('transition-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/automation/transitions/resolve')).toHaveLength(1);
    });
    const sent = fake.find('PUT', '/api/v1/automation/transitions/resolve')[0];
    expect(sent?.headers.get('If-Match')).toBe('"0"');
    expect((sent?.body as { relatives: string[] }).relatives).toEqual(['assignee']);
  });
});

describe('The record (WP-029 part 2)', () => {
  beforeEach(() => {
    setDefaultClientFactory(inertClientFactory);
    rememberTab(ADMIN.user.id, 'automation');
  });

  it('REQ-RUL-010: each action shows its outcome, a failure with its reason', async () => {
    routes({ [`GET ${PATH}/automation`]: { body: [run({})] } });
    open(`/incidents/${ITEM.id}`);
    const failed = await screen.findByTestId('inc-automation-action-0');
    expect(failed.textContent).toBe('Set Group: Failed (This group does not exist.)');
    expect(screen.getByTestId('inc-automation-action-1').textContent).toBe(
      'Add a private note: Done',
    );
  });

  it('C3: rules and routing in the save show on the Automation tab, not only in History', async () => {
    const step = (kind: string, extra: Record<string, unknown>) => ({
      change_id: `c-${kind}`,
      version: 1,
      kind: 'created',
      occurred_at: new Date().toISOString(),
      actor_id: null,
      actor_name: null,
      actor_type: 'system',
      source: 'rule',
      reason: null,
      changes: [],
      automation: { kind, ...extra },
    });
    routes({
      [`GET ${PATH}/history`]: {
        body: {
          items: [
            step('business_rule', { rule: 'Email is P2' }),
            step('routing', { reason: 'rule', rule: 'Network calls' }),
          ],
          next_cursor: null,
          people: {},
        },
      },
    });
    open(`/incidents/${ITEM.id}`);
    const steps = await screen.findByTestId('inc-automation-steps');
    expect(steps.textContent).toContain('Email is P2');
    expect(steps.textContent).toContain('Network calls');
    expect(screen.queryByTestId('inc-automation-empty')).toBeNull();
    expect(screen.getByTestId('inc-automation-history-hint')).toBeDefined();
  });

  it('REQ-RUL-028 AC1: a stopped loop warns on the record, naming the triggers', async () => {
    routes({
      [`GET ${PATH}/automation`]: {
        body: [
          run({
            id: 'run-2',
            kind: 'loop_guard',
            automation_name: 'Ping, Pong',
            outcome: 'chain_depth',
            detail: { triggers: ['Ping', 'Pong'], depth: 6 },
          }),
        ],
      },
    });
    open(`/incidents/${ITEM.id}`);
    const warning = await screen.findByTestId('inc-loop-warning');
    expect(warning.textContent).toContain('Ping and Pong');
  });

  it('REQ-WF-003: a move with a confirmation asks before it runs', async () => {
    const item: Incident = {
      ...ITEM,
      actions: ITEM.actions.map((a) =>
        a.action === 'resolve'
          ? { ...a, allowed: true, reason: null, confirmation: { en: 'Is the user happy?' } }
          : a,
      ),
    };
    const fake = routes({ [`GET ${PATH}`]: { body: item, headers: { ETag: '"1"' } } });
    open(`/incidents/${item.id}`);
    fireEvent.click(await screen.findByTestId('inc-action-resolve'));
    expect((await screen.findByTestId('inc-action-confirmation')).textContent).toBe(
      'Is the user happy?',
    );
    expect(fake.find('POST', `${PATH}/actions/resolve`)).toHaveLength(0);
  });

  it('REQ-WF-004: a move limited to others is shown disabled with the reason', async () => {
    const item: Incident = {
      ...ITEM,
      actions: ITEM.actions.map((a) =>
        a.action === 'resolve' ? { ...a, allowed: false, reason: 'not_for_you' } : a,
      ),
    };
    routes({ [`GET ${PATH}`]: { body: item, headers: { ETag: '"1"' } } });
    open(`/incidents/${item.id}`);
    const reason = await screen.findByTestId('inc-action-resolve-reason');
    expect(reason.getAttribute('data-reason')).toBe('not_for_you');
  });
});

describe('Admins are told about stopped loops (REQ-RUL-028 AC3)', () => {
  it('shows the banner with the triggers and links', async () => {
    routes({
      'GET /api/v1/automation/loop-stops': {
        body: [
          {
            id: 'run-2',
            record_type: 'incident',
            record_id: ITEM.id,
            cap: 'chain_depth',
            triggers: ['Ping', 'Pong'],
            occurred_at: new Date().toISOString(),
          },
        ],
      },
    });
    open('/');
    const banner = await screen.findByTestId('loop-banner');
    expect(banner.textContent).toContain('Automation stopped 1 loop in the last day.');
    expect(banner.textContent).toContain('Ping and Pong');
  });
});
