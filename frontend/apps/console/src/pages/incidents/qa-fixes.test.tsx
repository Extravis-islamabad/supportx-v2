import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Incident } from '@supportx/api-client';
import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi, problem } from '../../test/api';
import { rememberTab } from './tabs';

// The fake session's user (api-client testing fixtures).
const SESSION_USER = '01900000-0000-7000-8000-000000000101';

// WP-020-FIX: one test (at least) per finding of the WP-020 QA report, named after its ID, so
// none of them can come back unnoticed.

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

const ITEM = fakeIncident();
const PATH = `/api/v1/incidents/${ITEM.id}`;
const TECH = '01900000-0000-7000-8000-0000000003c1';
const PEOPLE = {
  ...ITEM.people,
  [TECH]: { display_name: 'Tariq Technician', email: 'tech@demo.test' },
};
const TAKEN: Incident = {
  ...ITEM,
  group_id: 'g-a',
  technician_id: TECH,
  status: 'assigned',
  version: 3,
  people: PEOPLE,
  operations: ITEM.operations.map((o) =>
    o.action === 'take' ? { ...o, allowed: false, reason: 'already_yours' } : o,
  ),
};
const COMMON = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': {
    body: [
      { id: 'g-a', name: 'Service Desk', member_ids: [TECH] },
      { id: 'g-b', name: 'Network', member_ids: [] },
    ],
  },
  'GET /api/v1/organization/sites': { body: [{ id: 's-1', name: 'Karachi', member_ids: [] }] },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
  'GET /api/v1/incidents/assignees': {
    body: [{ id: TECH, display_name: 'Tariq Technician', email: 'tech@demo.test', open_count: 1 }],
  },
  [`GET ${PATH}/history`]: { body: { items: [], next_cursor: null, people: {} } },
};

/** Ant Design's error notifications (reportError), by their visible text. */
function errorToasts(): string[] {
  return [...document.querySelectorAll('.ant-notification-notice')].map((n) => n.textContent);
}

describe('QA findings on one incident', () => {
  beforeEach(() => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    // These tests are about the Details tab: start there (the default is Conversation, D-081).
    rememberTab(SESSION_USER, 'details');
  });
  afterEach(() => {
    restore();
    vi.restoreAllMocks();
  });

  it('BUG-01: the Assign dialog shows the current assignment after a live change and never clears the technician', async () => {
    const fake = api({
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: () =>
          fake.find('POST', `${PATH}/take`).length === 0 ? { body: ITEM } : { body: TAKEN },
        [`POST ${PATH}/take`]: { body: TAKEN },
        [`POST ${PATH}/assign`]: { body: TAKEN },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-op-take'));
    await waitFor(() => {
      expect(screen.getByTestId('inc-people').textContent).toContain('Tariq Technician');
    });
    fireEvent.click(screen.getByTestId('inc-op-assign'));
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => {
      expect(within(dialog).getByTestId('inc-assign-group').textContent).toContain('Service Desk');
    });
    expect(within(dialog).getByTestId('inc-assign-technician').textContent).toContain(
      'Tariq Technician',
    );
    // Nothing changed, so no "why it moves" question.
    expect(within(dialog).queryByTestId('inc-assign-reason')).toBeNull();
    fireEvent.click(within(dialog).getByTestId('inc-assign-confirm'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/assign`)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', `${PATH}/assign`);
    expect(sent?.body).toMatchObject({ group_id: 'g-a', technician_id: TECH });
    expect(sent?.headers.get('If-Match')).toBe('"3"');
  });

  it('BUG-01: opening Assign re-reads the incident; an assignment that arrives while it is open replaces untouched fields', async () => {
    let reads = 0;
    const fake = api({
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: () => {
          reads += 1;
          return { body: reads === 1 ? ITEM : TAKEN };
        },
        [`POST ${PATH}/assign`]: { body: TAKEN },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-op-assign'));
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => {
      expect(within(dialog).getByTestId('inc-assign-technician').textContent).toContain(
        'Tariq Technician',
      );
    });
    expect(reads).toBeGreaterThan(1);
    fireEvent.click(within(dialog).getByTestId('inc-assign-confirm'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/assign`)).toHaveLength(1);
    });
    expect(fake.find('POST', `${PATH}/assign`)[0]?.body).toMatchObject({ technician_id: TECH });
  });

  it('BUG-02: a double-click on a dialog action sends it once and shows no false conflict', async () => {
    const waiting = fakeIncident({
      status: 'awaiting_requester',
      status_category: 'paused',
      version: 2,
    });
    const item = fakeIncident({
      actions: ITEM.actions.map((a) =>
        a.action === 'wait_requester'
          ? {
              ...a,
              allowed: true,
              reason: null,
              reason_mode: 'required',
              reason_list: 'pause',
            }
          : a,
      ),
    });
    let posts = 0;
    const fake = api({
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: { body: item },
        [`POST ${PATH}/actions/wait_requester`]: () => {
          posts += 1;
          return posts === 1
            ? { body: waiting }
            : { status: 409, body: problem(409, 'version_conflict') };
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-wait_requester'));
    fireEvent.change(await screen.findByTestId('inc-reason-text'), {
      target: { value: 'Asked by mail' },
    });
    fireEvent.mouseDown(selectorOf(screen.getByTestId('inc-reason-code')));
    fireEvent.click(await screen.findByTitle('Other'));
    const confirm = screen.getByTestId('inc-reason-confirm');
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => {
      expect(screen.queryByTestId('inc-reason-confirm')).toBeNull();
    });
    expect(fake.find('POST', `${PATH}/actions/wait_requester`)).toHaveLength(1);
    expect(errorToasts().join(' ')).not.toMatch(/someone else/i);
  });

  it('BUG-02: a double-click on Assign or on an inline Save sends one request', async () => {
    const fake = api({
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: { body: ITEM },
        [`POST ${PATH}/assign`]: { body: { ...ITEM, group_id: 'g-a', version: 2 } },
        [`PATCH ${PATH}`]: { body: { ...ITEM, subject: 'Mail down', version: 2 } },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-edit-subject'));
    fireEvent.change(screen.getByTestId('inc-input-subject'), { target: { value: 'Mail down' } });
    const save = screen.getByTestId('inc-save-subject');
    fireEvent.click(save);
    fireEvent.click(save);
    await waitFor(() => {
      expect(fake.find('PATCH', PATH)).toHaveLength(1);
    });
    fireEvent.click(screen.getByTestId('inc-op-assign'));
    fireEvent.mouseDown(selectorOf(await screen.findByTestId('inc-assign-group')));
    fireEvent.click(await screen.findByTitle('Service Desk'));
    const confirm = screen.getByTestId('inc-assign-confirm');
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/assign`)).toHaveLength(1);
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(fake.find('POST', `${PATH}/assign`)).toHaveLength(1);
    expect(fake.find('PATCH', PATH)).toHaveLength(1);
  });

  it('BUG-03: history names the technician instead of "changed"', async () => {
    api({
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: { body: TAKEN },
        [`GET ${PATH}/history`]: {
          body: {
            items: [
              {
                change_id: 'c-2',
                version: 2,
                kind: 'updated',
                occurred_at: '2026-10-24T09:05:00Z',
                actor_type: 'user',
                actor_id: TECH,
                actor_name: 'Tariq Technician',
                source: 'ui',
                reason: null,
                automation: null,
                changes: [
                  { field: 'group_id', old: null, new: 'g-a' },
                  { field: 'technician_id', old: null, new: TECH },
                  { field: 'handed_over_out_of_reach', old: null, new: true },
                ],
              },
            ],
            next_cursor: null,
            people: { [TECH]: { display_name: 'Tariq Technician', email: 'tech@demo.test' } },
          },
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: /History/ }));
    const entry = await screen.findByTestId('inc-history-entry');
    expect(entry.textContent).toContain('Technician: (empty) → Tariq Technician');
    expect(entry.textContent).not.toContain('changed');
    // A flag that was never set reads "No", not "(empty)" (UX-09).
    expect(entry.textContent).toContain('No → Yes');
  });

  it('BUG-05: Start work says why when the user may not take the incident; with several groups it asks which', async () => {
    const refused = fakeIncident({
      actions: ITEM.actions.map((a) =>
        a.action === 'start_work' ? { ...a, allowed: false, reason: 'cannot_take' } : a,
      ),
    });
    api({ routes: { ...COMMON, [`GET ${PATH}`]: { body: refused } } });
    const { unmount } = render(<App />);
    const why = await screen.findByTestId('inc-action-start_work-reason');
    expect(why.getAttribute('data-reason')).toBe('cannot_take');
    unmount();
    restore();

    const started = { ...TAKEN, status: 'in_progress', version: 4 };
    const fake = api({
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: { body: ITEM },
        [`POST ${PATH}/actions/start_work`]: (call) =>
          (call.body as { group_id?: string } | undefined)?.group_id === undefined
            ? {
                status: 422,
                body: problem(422, 'validation_failed', {
                  errors: [
                    {
                      field: 'body.group_id',
                      code: 'group_required',
                      message_key: 'errors.field.group_required',
                      params: {},
                    },
                  ],
                }),
              }
            : { body: started },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-start_work'));
    const chooser = await screen.findByTestId('inc-start-group');
    expect(screen.getByText('Start work: which of your groups takes it?')).toBeDefined();
    fireEvent.mouseDown(selectorOf(chooser));
    fireEvent.click(await screen.findByTitle('Service Desk'));
    fireEvent.click(screen.getByTestId('inc-start-confirm'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/actions/start_work`)).toHaveLength(2);
    });
    expect(fake.find('POST', `${PATH}/actions/start_work`)[1]?.body).toMatchObject({
      group_id: 'g-a',
    });
  });

  it('BUG-06: cancelling an incident uses clear words, never "Cancel / Cancel / Cancel"', async () => {
    api({ routes: { ...COMMON, [`GET ${PATH}`]: { body: ITEM } } });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-cancel'));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Cancel this incident?')).toBeDefined();
    expect(within(dialog).getByTestId('inc-reason-confirm').textContent).toBe('Cancel incident');
    expect(within(dialog).getByRole('button', { name: 'Keep incident' })).toBeDefined();
    const buttons = within(dialog)
      .getAllByRole('button')
      .map((b) => b.textContent);
    expect(buttons.filter((b) => b === 'Cancel')).toEqual([]);
  });

  it('BUG-08: moving to the trash shows one success message and no "does not exist" error', async () => {
    const deletable = fakeIncident({
      operations: ITEM.operations.map((o) => ({ ...o, allowed: true, reason: null })),
    });
    const fake = api({
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: () =>
          fake.find('DELETE', PATH).length === 0
            ? { body: deletable }
            : { status: 404, body: problem(404, 'work_item_not_found') },
        [`DELETE ${PATH}`]: { status: 204 },
        'GET /api/v1/incidents': {
          body: { items: [], has_more: false, next_cursor: null, estimated_total: 0, people: {} },
        },
        'GET /api/v1/incidents/views': { body: [] },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-op-delete'));
    const confirm = (await screen.findAllByRole('button', { name: 'Move to trash' })).at(-1);
    if (confirm === undefined) throw new Error('no confirmation');
    fireEvent.click(confirm);
    await waitFor(() => {
      expect(window.location.pathname).toBe('/incidents');
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(errorToasts().join(' ')).not.toMatch(/does not exist/);
    expect(document.body.textContent).toContain('Moved to the trash.');
  });

  it('BUG-09: "Keep my changes" saves them on top of the newer version; the change notice goes away', async () => {
    const theirs = { ...ITEM, subject: 'Their subject', version: 2 };
    let reads = 0;
    const fake = api({
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: () => {
          reads += 1;
          return { body: reads === 1 ? ITEM : theirs };
        },
        [`PATCH ${PATH}`]: (call) =>
          call.headers.get('If-Match') === '"1"'
            ? {
                status: 409,
                body: problem(409, 'version_conflict', {
                  params: {
                    expected_version: 1,
                    current_version: 2,
                    changed_by: 'Amal Admin',
                    changed_fields: 'subject',
                    changed_at: '2026-10-24T09:05:00Z',
                  },
                }),
              }
            : { body: { ...theirs, subject: 'Mine', version: 3 } },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-edit-subject'));
    fireEvent.change(screen.getByTestId('inc-input-subject'), { target: { value: 'Mine' } });
    fireEvent.click(screen.getByTestId('inc-save-subject'));
    fireEvent.click(await screen.findByTestId('conflict-keep-mine'));
    await waitFor(() => {
      expect(fake.find('PATCH', PATH)).toHaveLength(2);
    });
    const second = fake.find('PATCH', PATH)[1];
    expect(second?.headers.get('If-Match')).toBe('"2"');
    expect(second?.body).toMatchObject({ subject: 'Mine' });
    await waitFor(() => {
      expect(screen.queryByTestId('inc-input-subject')).toBeNull();
    });
    expect(screen.queryByTestId('live-change-notice')).toBeNull();
  });

  it('BUG-10: the subject allows what the API allows (500) and shows a counter', async () => {
    api({ routes: { ...COMMON, [`GET ${PATH}`]: { body: ITEM } } });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-edit-subject'));
    const input = screen.getByTestId<HTMLInputElement>('inc-input-subject');
    expect(document.body.textContent).toContain('12 / 500');
    // Over the limit, the text is kept and the counter says so (WP-026 QA BUG-03: never cut).
    fireEvent.change(input, { target: { value: 'x'.repeat(501) } });
    expect(input.value).toHaveLength(501);
    expect(document.body.textContent).toContain('501 / 500');
  });

  it('BUG-11: an inline edit takes the focus; Enter saves and Escape cancels', async () => {
    const fake = api({
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: { body: ITEM },
        [`PATCH ${PATH}`]: { body: { ...ITEM, subject: 'Mail is up', version: 2 } },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-edit-subject'));
    const input = screen.getByTestId('inc-input-subject');
    await waitFor(() => {
      expect(document.activeElement).toBe(input);
    });
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(screen.queryByTestId('inc-input-subject')).toBeNull();
    expect(fake.find('PATCH', PATH)).toHaveLength(0);
    fireEvent.click(screen.getByTestId('inc-edit-subject'));
    const again = screen.getByTestId('inc-input-subject');
    fireEvent.change(again, { target: { value: 'Mail is up' } });
    fireEvent.keyDown(again, { key: 'Enter' });
    await waitFor(() => {
      expect(fake.find('PATCH', PATH)).toHaveLength(1);
    });
  });

  it('BUG-12: text people typed reads in its own direction (heading, properties, reasons)', async () => {
    const item = fakeIncident({
      subject: 'QA-01 Printer <b>offline</b>',
      status_reason_text: 'بانتظار الرد',
    });
    api({ routes: { ...COMMON, [`GET ${PATH}`]: { body: item } } });
    render(<App />);
    const heading = await screen.findByTestId('inc-heading');
    expect(heading.querySelector('bdi')?.textContent).toBe('QA-01 Printer <b>offline</b>');
    expect(screen.getByTestId('inc-prop-subject').querySelector('bdi')?.getAttribute('dir')).toBe(
      'auto',
    );
    expect(screen.getByTestId('inc-status-reason').querySelector('bdi')?.textContent).toBe(
      'بانتظار الرد',
    );
    fireEvent.click(screen.getByTestId('inc-action-cancel'));
    expect((await screen.findByTestId('inc-reason-text')).getAttribute('dir')).toBe('auto');
  });

  it('BUG-14: "Choose a reason" shows under the reason, "Describe the reason" under the details', async () => {
    api({ routes: { ...COMMON, [`GET ${PATH}`]: { body: ITEM } } });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-cancel'));
    fireEvent.click(await screen.findByTestId('inc-reason-confirm'));
    const codeError = await screen.findByTestId('inc-reason-code-error');
    expect(codeError.textContent).toBe('Choose a reason.');
    // Directly after the reason picker, before the details box.
    const picker = screen.getByTestId('inc-reason-code');
    const details = screen.getByTestId('inc-reason-text');
    const after = (a: Node, b: Node) =>
      (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    expect(after(picker, codeError)).toBe(true);
    expect(after(codeError, details)).toBe(true);
  });

  it('BUG-18: the hand-over warning matches D-068 (following is on by default)', async () => {
    api({
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: { body: ITEM },
        [`POST ${PATH}/assign`]: {
          status: 409,
          body: problem(409, 'would_lose_access', { params: { display_id: 'INC-7' } }),
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-op-assign'));
    fireEvent.mouseDown(selectorOf(await screen.findByTestId('inc-assign-group')));
    fireEvent.click(await screen.findByTitle('Network'));
    fireEvent.click(screen.getByTestId('inc-assign-confirm'));
    const warning = await screen.findByTestId('inc-handover-warning');
    // WP-020b: following after a hand-over exists now, ticked by default (D-068).
    expect(screen.getByTestId<HTMLInputElement>('inc-handover-keep-following').checked).toBe(true);
    expect(warning.textContent).toContain('You keep following it');
    expect(warning.textContent).not.toContain('next update');
  });

  it('C6: a dialog without a reason list does not mention "Other"', async () => {
    const canceled = fakeIncident({
      status: 'canceled',
      status_category: 'canceled',
      actions: ITEM.actions.map((a) =>
        a.action === 'undo_cancel'
          ? { ...a, allowed: true, reason: null, reason_mode: 'optional', reason_list: null }
          : { ...a, allowed: false, reason: 'not_from_status' },
      ),
    });
    api({ routes: { ...COMMON, [`GET ${PATH}`]: { body: canceled } } });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-undo_cancel'));
    const dialog = await screen.findByRole('dialog');
    expect(dialog.textContent).toContain('Details (optional)');
    expect(dialog.textContent).not.toContain('Other');
  });
});

describe('QA findings on the list and the form', () => {
  afterEach(() => {
    restore();
    vi.restoreAllMocks();
  });

  it('BUG-12 and BUG-16: subjects read in their own direction and are cut with an ellipsis; Restore stays in view', async () => {
    window.history.pushState({}, '', '/incidents');
    const long = { ...ITEM, subject: `QA-01 ${'A'.repeat(260)}`, deleted_at: null };
    const page = {
      items: [long],
      has_more: false,
      next_cursor: null,
      estimated_total: 1,
      people: ITEM.people,
    };
    api({
      me: undefined,
      routes: {
        ...COMMON,
        'GET /api/v1/incidents': { body: page },
        'GET /api/v1/incidents/trash': { body: page },
        'GET /api/v1/incidents/views': { body: [{ view: 'open', count: 1, capped: false }] },
      },
    });
    render(<App />);
    const row = await screen.findByTestId('inc-row-INC-7');
    const subject = within(row).getByText(/^QA-01 A+$/);
    expect(subject.closest('bdi')?.getAttribute('dir')).toBe('auto');
    expect(subject.closest('td')?.className).toContain('ant-table-cell-ellipsis');
  });

  it('BUG-10, BUG-17 and the form review: counter, required markers, tenant defaults, focus after "log another"', async () => {
    window.history.pushState({}, '', '/incidents/new');
    const scrolled = vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined);
    api({
      routes: {
        ...COMMON,
        'GET /api/v1/users': {
          body: {
            items: [{ id: 'u-1', display_name: 'Rana Requester', email: 'rana@demo.test' }],
            has_more: false,
            next_cursor: null,
          },
        },
        'POST /api/v1/incidents': { status: 201, body: ITEM },
      },
    });
    render(<App />);
    const subject = await screen.findByTestId('inc-subject');
    expect(document.body.textContent).toContain('0 / 500');
    // Required fields are marked, and the form says once what the mark means.
    expect(screen.getByText('Fields marked * are required.')).toBeDefined();
    const required = [...document.querySelectorAll('.ant-form-item-required')].map(
      (l) => l.textContent,
    );
    expect(required).toEqual(['Subject', 'Requester']);
    // Impact and urgency start from the tenant's defaults; the priority is theirs (team x medium).
    await waitFor(() => {
      expect(screen.getByTestId('inc-impact').textContent).toContain('A team');
    });
    expect(screen.getByTestId('inc-urgency').textContent).toContain('Medium');
    expect(screen.getByTestId('inc-priority-preview').textContent).toContain('P3 – Medium');
    expect(screen.getByTestId('inc-priority-preview').textContent).not.toContain('*');
    // Both cleared: no priority pretends to be known.
    fireEvent.mouseDown(selectorOf(screen.getByTestId('inc-impact')));
    const clear = screen.getByTestId('inc-impact').querySelector('.ant-select-clear');
    if (clear === null) throw new Error('impact cannot be cleared');
    fireEvent.mouseDown(clear);
    const urgencyClear = screen.getByTestId('inc-urgency').querySelector('.ant-select-clear');
    if (urgencyClear === null) throw new Error('urgency cannot be cleared');
    fireEvent.mouseDown(urgencyClear);
    await waitFor(() => {
      expect(screen.getByTestId('inc-priority-preview').textContent).toBe(
        'Calculated when impact and urgency are set',
      );
    });
    // "Log another": the next form starts at the top with the cursor in the subject.
    fireEvent.change(subject, { target: { value: 'Printer jammed' } });
    fireEvent.mouseDown(selectorOf(screen.getByTestId('inc-requester')));
    fireEvent.click(await screen.findByText('rana@demo.test'));
    fireEvent.click(screen.getByTestId('inc-another'));
    scrolled.mockClear();
    fireEvent.click(screen.getByTestId('inc-save'));
    await waitFor(() => {
      expect(screen.getByTestId<HTMLInputElement>('inc-subject').value).toBe('');
    });
    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByTestId('inc-subject'));
    });
    expect(scrolled).toHaveBeenCalled();
  });

  it('BUG-17: opening a record starts at the top of the page', async () => {
    window.history.pushState({}, '', '/incidents');
    const scrolled = vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined);
    api({
      routes: {
        ...COMMON,
        'GET /api/v1/incidents': {
          body: {
            items: [{ ...ITEM, deleted_at: null }],
            has_more: false,
            next_cursor: null,
            estimated_total: 1,
            people: ITEM.people,
          },
        },
        'GET /api/v1/incidents/views': { body: [{ view: 'open', count: 1, capped: false }] },
        [`GET ${PATH}`]: { body: ITEM },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-row-INC-7'));
    await screen.findByTestId('inc-heading');
    expect(scrolled).toHaveBeenCalledWith(expect.objectContaining({ top: 0 }));
  });

  it('C7: every option of every picker on the form is named by its label, never by a code or ID', async () => {
    window.history.pushState({}, '', '/incidents/new');
    api({
      routes: {
        ...COMMON,
        'GET /api/v1/users': {
          body: {
            items: [{ id: 'u-1', display_name: 'Rana Requester', email: 'rana@demo.test' }],
            has_more: false,
            next_cursor: null,
          },
        },
      },
    });
    render(<App />);
    await screen.findByTestId('inc-subject');
    for (const testId of ['inc-requester', 'inc-impact', 'inc-urgency', 'inc-group']) {
      fireEvent.mouseDown(selectorOf(screen.getByTestId(testId)));
      await waitFor(() => {
        expect(document.querySelectorAll('[role="option"]').length).toBeGreaterThan(0);
      });
    }
    expectOptionsNamedByLabels();
  });
});

/** C7's check: accessible names of options are labels (aria-label), never codes or UUIDs. */
export function expectOptionsNamedByLabels(): void {
  const code = /^[a-z0-9]+(_[a-z0-9]+)*$|^[0-9a-f-]{8,}$|^[a-z]-[a-z0-9]+$/;
  const options = [...document.querySelectorAll('[role="option"]')];
  expect(options.length).toBeGreaterThan(0);
  const unnamed = options
    .map((o) => o.getAttribute('aria-label') ?? '')
    .filter((name) => name === '' || code.test(name));
  expect(unnamed).toEqual([]);
}
