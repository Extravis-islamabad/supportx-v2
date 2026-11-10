import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi, fakeSession, problem } from '../../test/api';
import { duplicateNames } from './labels';
import { previewPriority } from './form';
import { rememberTab } from './tabs';
import { actionOrder, clickAction, isDisabled } from '../../test/actions';

// The fake session's user (api-client testing fixtures).
const SESSION_USER = '01900000-0000-7000-8000-000000000101';

// WP-020 screens. Test names cite docs/specs/parity/01-work-items-incidents.md criteria.

/** The clickable part of an Ant Design Select (mouse-down opens it). */
function selectorOf(select: HTMLElement): Element {
  const found = select.querySelector('.ant-select-selector');
  if (found === null) throw new Error('not an Ant Design Select');
  return found;
}

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const ITEM = fakeIncident();
const PATH = `/api/v1/incidents/${ITEM.id}`;
const COMMON = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': {
    body: [{ id: 'g-a', name: 'Service Desk', member_ids: [] }],
  },
  'GET /api/v1/organization/sites': { body: [{ id: 's-1', name: 'Karachi', member_ids: [] }] },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
};
const VIEWS = [
  { view: 'open', count: 3, capped: false },
  { view: 'my_open', count: 1, capped: false },
  { view: 'all', count: 8, capped: false },
];

function listRoutes(items = [ITEM]) {
  return {
    ...COMMON,
    'GET /api/v1/incidents': {
      body: {
        items: items.map((i) => ({ ...i, deleted_at: null })),
        has_more: false,
        next_cursor: null,
        estimated_total: items.length,
        people: ITEM.people,
      },
    },
    'GET /api/v1/incidents/views': { body: VIEWS },
  };
}

describe('Incidents list', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/incidents');
  });
  afterEach(() => {
    restore();
  });

  it('REQ-INC-104/105: labels, never codes; the default view says what it leaves out (Area 15)', async () => {
    api({ routes: listRoutes() });
    render(<App />);
    const row = await screen.findByTestId('inc-row-INC-7');
    expect(within(row).getByText('New')).toBeDefined();
    expect(within(row).getByText('Rana Requester')).toBeDefined();
    expect(within(row).getByText('No SLA applies')).toBeDefined(); // REQ-INC-011 AC2
    expect(row.textContent).not.toMatch(/\bnew\b|p3|not_from_status/);
    const notice = await screen.findByTestId('inc-view-notice');
    expect(notice.textContent).toContain('View “All open”: 3 shown.');
    expect(notice.textContent).toContain('5 other incidents you can see are not in this view.');
    expect(notice.querySelector('[data-hidden]')?.getAttribute('data-hidden')).toBe('5');
    expect(screen.getByTestId('inc-show-all')).toBeDefined();
  });

  it('REQ-INC-109: one search box for subject words or a display ID', async () => {
    const fake = api({ routes: listRoutes() });
    render(<App />);
    await screen.findByTestId('inc-row-INC-7');
    fireEvent.change(screen.getByRole('combobox', { name: 'Search subject or ID' }), {
      target: { value: 'INC-7' },
    });
    await waitFor(() => {
      const last = fake.find('GET', '/api/v1/incidents').at(-1);
      expect(JSON.parse(last?.url.searchParams.get('filter') ?? 'null')).toEqual({
        or: [
          { field: 'subject', op: 'contains', value: 'INC-7' },
          { field: 'display_number', op: 'eq', value: 7 },
        ],
      });
    });
    expect(fake.find('GET', '/api/v1/incidents')[0]?.url.searchParams.get('view')).toBe('open');
  });
});

describe('One incident', () => {
  beforeEach(() => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    // These tests are about the Details tab: start there (the default is Conversation, D-081).
    rememberTab(SESSION_USER, 'details');
  });
  afterEach(() => {
    restore();
  });

  it('REQ-WI-010/011: actions in one fixed order, disabled ones say why; fixed tabs; rich text shown', async () => {
    api({ routes: { ...COMMON, [`GET ${PATH}`]: { body: ITEM, headers: { ETag: '"1"' } } } });
    render(<App />);
    expect((await screen.findByTestId('inc-heading')).textContent).toBe('Mail is down');
    // Every move in "More actions": the available ones first, then the unavailable ones under
    // their reason, each part in the fixed order (D-124; QA6-INC-02); destructive last.
    const order = (await actionOrder()).filter((id) => id.startsWith('inc-action-'));
    expect(order).toEqual([
      'inc-action-start_work',
      'inc-action-resolve',
      'inc-action-wait_requester',
      'inc-action-wait_third_party',
      'inc-action-resume',
      'inc-action-close',
      'inc-action-reopen',
      'inc-action-undo_cancel',
      // Destructive moves sit apart, last (REQ-WI-010 AC4).
      'inc-action-cancel',
    ]);
    const close = screen.getByTestId('inc-action-close-menu');
    expect(isDisabled(close)).toBe(true);
    expect(close.textContent).toContain('Not possible in the current status.');
    // Delete is not offered at all without the permission (it is set apart from everyday work).
    expect(screen.queryByTestId('inc-op-delete')).toBeNull();
    const tabs = screen.getAllByRole('tab').map((tab) => tab.textContent);
    expect(tabs).toEqual([
      'Conversation (1)', // the description, and no replies or notes yet
      'Details',
      'Tasks',
      'Worklogs',
      'Links',
      'History (1)',
      'Automation',
    ]);
    const description = await screen.findByTestId('inc-description');
    expect(description.innerHTML).toBe('<p>Since <strong>9:00</strong>.</p>');
    expect(description.getAttribute('dir')).toBe('auto');
  });

  it('D-124 and UI pass 2: Reply is primary, the best-ranked moves fill the rest; the others stay in the menu', async () => {
    const open = fakeIncident({
      actions: ITEM.actions.map((a) => ({
        ...a,
        allowed: ['start_work', 'wait_requester', 'wait_third_party', 'resolve', 'close'].includes(
          a.action,
        ),
        reason: null,
      })),
      operations: ITEM.operations.map((o) => ({ ...o, allowed: false, reason: 'no_permission' })),
    });
    api({ routes: { ...COMMON, [`GET ${PATH}`]: { body: open, headers: { ETag: '"1"' } } } });
    render(<App />);
    const bar = await screen.findByTestId('inc-operations');
    const buttons = within(bar)
      .getAllByRole('button')
      .map((b) => b.getAttribute('data-testid'))
      .filter((id) => id?.startsWith('inc-action-'));
    // Three buttons and More actions (at most four controls, UI pass 2): Reply first and primary,
    // then the best-ranked moves (resolve, start work); close and the waits stay in the menu.
    expect(buttons).toEqual(['inc-action-start_work', 'inc-action-resolve']);
    expect(screen.getByTestId('inc-op-reply').className).toContain('ant-btn-primary');
    expect(screen.getByTestId('inc-action-resolve').className).not.toContain('ant-btn-primary');
  });

  it('REQ-WI-010 AC4: a cancel without a reason step still asks once, in clear words', async () => {
    const plain = fakeIncident({
      actions: ITEM.actions.map((a) =>
        a.action === 'cancel' ? { ...a, allowed: true, reason: null, reason_mode: 'none' } : a,
      ),
    });
    const canceled = fakeIncident({ status: 'canceled', status_category: 'canceled', version: 2 });
    const fake = api({
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: { body: plain, headers: { ETag: '"1"' } },
        [`POST ${PATH}/actions/cancel`]: { body: canceled },
      },
    });
    render(<App />);
    await clickAction('inc-action-cancel');
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getAllByText('Cancel this incident?').length).toBeGreaterThan(0);
    expect(fake.find('POST', `${PATH}/actions/cancel`)).toHaveLength(0);
    expect(within(dialog).queryByRole('button', { name: 'Cancel' })).toBeNull();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel incident' }));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/actions/cancel`)).toHaveLength(1);
    });
  });

  it('REQ-INC-047: an action that needs a reason asks for it before sending', async () => {
    const canceled = fakeIncident({ status: 'canceled', status_category: 'canceled', version: 2 });
    const fake = api({
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: { body: ITEM, headers: { ETag: '"1"' } },
        [`POST ${PATH}/actions/cancel`]: { body: canceled },
      },
    });
    render(<App />);
    await clickAction('inc-action-cancel');
    fireEvent.click(await screen.findByTestId('inc-reason-confirm'));
    expect((await screen.findByTestId('inc-reason-code-error')).textContent).toBe(
      'Choose a reason.',
    );
    expect(fake.find('POST', `${PATH}/actions/cancel`)).toHaveLength(0);
    fireEvent.mouseDown(selectorOf(screen.getByTestId('inc-reason-code')));
    fireEvent.click(await screen.findByTitle('Duplicate'));
    fireEvent.click(screen.getByTestId('inc-reason-confirm'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/actions/cancel`)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', `${PATH}/actions/cancel`);
    expect(sent?.body).toEqual({
      reason_code: 'duplicate',
      reason_text: null,
      confirm_open_work: false,
    });
    expect(sent?.headers.get('If-Match')).toBe('"1"');
  });

  it('D-053/D-068: a hand-over warns first; unticking "keep following" gives up access', async () => {
    const handed = {
      ...ITEM,
      group_id: 'g-a',
      version: 2,
      visible: false,
      actions: [],
      operations: [],
    };
    const fake = api({
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: { body: ITEM, headers: { ETag: '"1"' } },
        'GET /api/v1/incidents/assignees': { body: [] },
        'GET /api/v1/incidents': listRoutes()['GET /api/v1/incidents'],
        'GET /api/v1/incidents/views': { body: VIEWS },
        [`POST ${PATH}/assign`]: (call) =>
          (call.body as { confirm_lose_access: boolean }).confirm_lose_access
            ? { body: handed }
            : {
                status: 409,
                body: problem(409, 'would_lose_access', { params: { display_id: 'INC-7' } }),
              },
      },
    });
    render(<App />);
    await clickAction('inc-op-assign');
    fireEvent.mouseDown(selectorOf(await screen.findByTestId('inc-assign-group')));
    fireEvent.click(await screen.findByTitle('Service Desk'));
    fireEvent.click(screen.getByTestId('inc-assign-confirm'));
    const warning = await screen.findByTestId('inc-handover-warning');
    expect(warning.textContent).toContain('INC-7 moves to Service Desk');
    // D-068: keep following is ticked by default, and says what that means.
    // antd puts the test ID on the checkbox input itself.
    const keep = screen.getByTestId<HTMLInputElement>('inc-handover-keep-following');
    expect(keep.checked).toBe(true);
    expect(warning.textContent).toContain('You keep following it');
    fireEvent.click(keep);
    expect(screen.getByTestId('inc-handover-outcome').textContent).toContain(
      'You will no longer be able to see INC-7',
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId('inc-handover-confirm'));
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/assign`)).toHaveLength(2);
    });
    const [first, second] = fake.find('POST', `${PATH}/assign`);
    expect((first?.body as { confirm_lose_access: boolean }).confirm_lose_access).toBe(false);
    expect((second?.body as { confirm_lose_access: boolean }).confirm_lose_access).toBe(true);
    expect((second?.body as { keep_following: boolean }).keep_following).toBe(false);
    await waitFor(() => {
      expect(window.location.pathname).toBe('/incidents');
    });
  });

  it('REQ-INC-122 AC1: while an incident loads only a skeleton shows, keyed by its ID', async () => {
    let release: () => void = () => undefined;
    const other = fakeIncident({
      id: '01900000-0000-7000-8000-00000000c002',
      display_id: 'INC-8',
      subject: 'VPN',
    });
    window.history.pushState({}, '', `/incidents/${other.id}`);
    api({
      routes: {
        ...COMMON,
        [`GET /api/v1/incidents/${other.id}`]: () =>
          new Promise((resolve) => {
            release = () => {
              resolve({ body: other });
            };
          }),
      },
    });
    render(<App />);
    await screen.findByTestId('inc-loading');
    expect(screen.queryByTestId('inc-heading')).toBeNull();
    act(() => {
      release();
    });
    expect((await screen.findByTestId('inc-heading')).textContent).toBe('VPN');
  });

  it('REQ-WI-007 AC2: a stale inline edit explains who changed what and keeps the edit open', async () => {
    api({
      me: ADMIN,
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: { body: ITEM },
        [`PATCH ${PATH}`]: {
          status: 409,
          body: problem(409, 'version_conflict', {
            params: {
              expected_version: 1,
              current_version: 2,
              changed_by: 'Tariq Technician',
              changed_fields: 'subject',
              changed_at: '2026-10-24T09:05:00Z',
            },
          }),
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-edit-subject'));
    fireEvent.change(screen.getByTestId('inc-input-subject'), { target: { value: 'Mine' } });
    fireEvent.click(screen.getByTestId('inc-save-subject'));
    expect((await screen.findByTestId('conflict-who')).textContent).toContain(
      'Tariq Technician saved it at',
    );
    expect(screen.getByTestId('inc-input-subject')).toBeDefined();
  });
});

describe('New incident', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/incidents/new');
  });
  afterEach(() => {
    restore();
  });

  it('REQ-WI-008: one Idempotency-Key per form, reused on a retry; the form is validated first', async () => {
    let calls = 0;
    const fake = api({
      routes: {
        ...COMMON,
        'GET /api/v1/users': {
          body: {
            items: [
              { id: 'u-1', display_name: 'Rana Requester', email: 'rana@demo.test' },
              { id: 'u-2', display_name: 'Rana Requester', email: 'rana.k@demo.test' },
            ],
            has_more: false,
            next_cursor: null,
          },
        },
        'POST /api/v1/incidents': () => {
          calls += 1;
          return calls === 1 ? 'network-error' : { status: 201, body: ITEM };
        },
        [`GET ${PATH}`]: { body: ITEM },
      },
    });
    render(<App />);
    // QA10-P1-16: a sticky footer, Cancel before Save.
    const footer = await screen.findByTestId('inc-new-footer');
    expect(footer.style.position).toBe('sticky');
    const ids = within(footer)
      .getAllByRole('button')
      .map((b) => b.getAttribute('data-testid'));
    expect(ids.indexOf('inc-new-cancel')).toBeLessThan(ids.indexOf('inc-save'));
    fireEvent.click(await screen.findByTestId('inc-save'));
    expect((await screen.findByTestId('error-subject')).textContent).toBe(
      'This field is required.',
    );
    expect(fake.find('POST', '/api/v1/incidents')).toHaveLength(0);
    fireEvent.change(screen.getByTestId('inc-subject'), { target: { value: 'Printer jammed' } });
    fireEvent.mouseDown(selectorOf(screen.getByTestId('inc-requester')));
    // Two people with the same name are told apart by their email (Area 15).
    expect(await screen.findByText('rana.k@demo.test')).toBeDefined();
    fireEvent.click(await screen.findByText('rana@demo.test'));
    fireEvent.click(screen.getByTestId('inc-save'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/incidents')).toHaveLength(1);
    });
    fireEvent.click(screen.getByTestId('inc-save'));
    await waitFor(() => {
      expect(window.location.pathname).toBe(`/incidents/${ITEM.id}`);
    });
    const [first, second] = fake.find('POST', '/api/v1/incidents');
    expect(first?.headers.get('Idempotency-Key')).toBeTruthy();
    // The network error is not "corrected input": a retry of the same body would be the same key,
    // but the client cannot tell, so it uses a new key only for changed input. Here the body
    // is unchanged, so the server's replay guard sees one create.
    expect(second?.body).toEqual(first?.body);
  });
});

describe('helpers', () => {
  it('REQ-INC-009 AC2: the form shows the matrix priority before saving', () => {
    const catalogue = fakeIncidentCatalogue();
    expect(previewPriority(catalogue, 'organisation', 'critical')).toEqual({
      priority: 'p1',
      source: 'matrix',
    });
    // Blank impact or urgency: no priority is shown as known (form review, WP-020-FIX).
    expect(previewPriority(catalogue, null, null)).toBeNull();
    expect(previewPriority(catalogue, 'team', null)).toBeNull();
  });

  it('Area 15: duplicate display names are found case- and space-insensitively', () => {
    expect([...duplicateNames(['Ali Khan', 'ali khan ', 'Sara'])]).toEqual(['ali khan']);
  });
});
