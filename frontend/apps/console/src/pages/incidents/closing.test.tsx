import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { Incident } from '@supportx/api-client';
import {
  fakeConversationEntry,
  fakeCustomField,
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi, fakeSession, problem } from '../../test/api';
import { rememberTab } from './tabs';

// WP-020f: resolving and closing on the record (docs/specs/parity/01-work-items-incidents.md,
// REQ-INC-090..098). Test names cite the requirement.

const SESSION_USER = '01900000-0000-7000-8000-000000000101';

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

/** In progress: resolve allowed; close allowed only where a test says so. */
function inProgress(missing: string[] = [], overrides: Partial<Incident> = {}): Incident {
  const base = fakeIncident({ status: 'in_progress', version: 4 });
  return {
    ...base,
    actions: base.actions.map((a) =>
      a.action === 'resolve' ? { ...a, allowed: true, reason: null, missing } : a,
    ),
    ...overrides,
  };
}

function resolvedItem(missing: string[] = []): Incident {
  const base = fakeIncident({
    status: 'resolved',
    status_category: 'resolved',
    version: 5,
    resolution: '<p>Restarted the <strong>mail relay</strong>.</p>',
  });
  return {
    ...base,
    actions: base.actions.map((a) =>
      a.action === 'close' ? { ...a, allowed: true, reason: null, missing } : a,
    ),
  };
}

const ITEM = fakeIncident();
const PATH = `/api/v1/incidents/${ITEM.id}`;
const COST = fakeCustomField({ key: 'cost', labels: { en: 'Repair cost', ar: 'تكلفة الإصلاح' } });
const COMMON = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/organization/departments': { body: [] },
  'GET /api/v1/custom-fields': { body: [COST] },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
  [`GET ${PATH}/conversation`]: { body: { items: [], people: {} } },
  [`GET ${PATH}/automation`]: { body: [] },
};

function record(item: Incident) {
  return { [`GET ${PATH}`]: { body: item, headers: { ETag: `"${String(item.version)}"` } } };
}

/** Type into the Tiptap editor of a dialog (typing into ProseMirror in jsdom is unreliable). */
async function typeRichText(testId: string, html: string) {
  const editor = await screen.findByTestId(testId);
  const tiptap = (
    editor as HTMLElement & { editor: { commands: { insertContent: (h: string) => void } } }
  ).editor;
  act(() => {
    tiptap.commands.insertContent(html);
  });
}

beforeEach(() => {
  localStorage.clear();
  window.history.pushState({}, '', `/incidents/${ITEM.id}`);
  rememberTab(SESSION_USER, 'details');
});
afterEach(() => {
  restore();
});

describe('Resolving', () => {
  it('REQ-INC-090: resolve asks for a resolution and sends it with the move', async () => {
    const fake = api({
      routes: {
        ...COMMON,
        ...record(inProgress()),
        [`POST ${PATH}/actions/resolve`]: { body: resolvedItem() },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-resolve'));
    fireEvent.click(await screen.findByTestId('inc-reason-confirm'));
    expect((await screen.findByTestId('inc-resolution-error')).textContent).toBe(
      'Describe how it was resolved.',
    );
    expect(fake.find('POST', `${PATH}/actions/resolve`)).toHaveLength(0);
    await typeRichText('inc-resolution-editor', 'Restarted the mail relay');
    fireEvent.click(screen.getByTestId('inc-reason-confirm'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/actions/resolve`)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', `${PATH}/actions/resolve`);
    expect(sent?.body).toMatchObject({
      resolution: '<p dir="auto">Restarted the mail relay</p>',
      confirm_open_work: false,
    });
    expect(sent?.headers.get('If-Match')).toBe('"4"');
  });

  it('REQ-INC-094: a closure code required to resolve is asked by the resolve dialog', async () => {
    const catalogue = fakeIncidentCatalogue();
    catalogue.closure = {
      ...catalogue.closure,
      resolve_requires: ['resolution', 'closure_code'],
    };
    const fake = api({
      routes: {
        ...COMMON,
        'GET /api/v1/incidents/settings': { body: catalogue },
        ...record(inProgress()),
        [`POST ${PATH}/actions/resolve`]: { body: resolvedItem() },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-resolve'));
    await typeRichText('inc-resolution-editor', 'Swapped the toner');
    fireEvent.mouseDown(selectorOf(await screen.findByTestId('inc-closure-code')));
    fireEvent.click(await screen.findByTitle('Workaround given'));
    fireEvent.click(screen.getByTestId('inc-reason-confirm'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/actions/resolve`)).toHaveLength(1);
    });
    expect(fake.find('POST', `${PATH}/actions/resolve`)[0]?.body).toMatchObject({
      closure_code: 'workaround',
    });
  });

  it('D-107: re-resolving a reopened incident offers the earlier resolution to reuse', async () => {
    const reopened = inProgress([], { reopen_count: 1, resolution: null });
    const fake = api({
      routes: {
        ...COMMON,
        ...record(reopened),
        [`GET ${PATH}/history`]: {
          body: {
            items: [
              {
                change_id: 'c-reopen',
                version: 6,
                kind: 'status',
                occurred_at: new Date().toISOString(),
                actor_id: null,
                actor_name: 'Amal Admin',
                actor_type: 'user',
                source: 'ui',
                reason: 'Still jams',
                automation: null,
                changes: [{ field: 'resolution', old: '<p>Rebooted the printer</p>', new: null }],
              },
            ],
            next_cursor: null,
            people: {},
          },
        },
        [`POST ${PATH}/actions/resolve`]: { body: resolvedItem() },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-resolve'));
    const earlier = await screen.findByTestId('inc-previous-resolution');
    expect(earlier.textContent).toContain('Rebooted the printer');
    fireEvent.click(screen.getByTestId('inc-previous-resolution-reuse'));
    await waitFor(() => {
      expect(screen.queryByTestId('inc-previous-resolution')).toBeNull();
    });
    fireEvent.click(screen.getByTestId('inc-reason-confirm'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/actions/resolve`)).toHaveLength(1);
    });
    expect(fake.find('POST', `${PATH}/actions/resolve`)[0]?.body).toMatchObject({
      resolution: '<p>Rebooted the printer</p>',
    });
  });

  it('REQ-INC-094: the dialog names the fields to fill on the record first, in words', async () => {
    api({
      routes: { ...COMMON, ...record(inProgress(['category_id', 'site_id', 'custom.cost'])) },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-resolve'));
    const missing = await screen.findByTestId('inc-closing-missing');
    await waitFor(() => {
      expect(missing.textContent).toBe(
        'Fill these on the record first: Category, Site, Repair cost.',
      );
    });
    expect(missing.textContent).not.toContain('category_id');
    expect(screen.getByTestId<HTMLButtonElement>('inc-reason-confirm').disabled).toBe(true);
  });

  it('REQ-INC-094: a closure-rules refusal names the record fields at the dialog', async () => {
    api({
      routes: {
        ...COMMON,
        ...record(inProgress()),
        [`POST ${PATH}/actions/resolve`]: {
          status: 422,
          body: problem(422, 'closure_rules', {
            errors: [
              {
                field: 'body.category_id',
                code: 'required_to_resolve',
                message_key: 'errors.field.required_to_resolve',
                params: {},
              },
            ],
          }),
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-resolve'));
    await typeRichText('inc-resolution-editor', 'Fixed');
    fireEvent.click(screen.getByTestId('inc-reason-confirm'));
    expect((await screen.findByTestId('inc-closing-missing')).textContent).toBe(
      'Fill these on the record first: Category.',
    );
  });

  it('REQ-INC-095: open work is listed; confirming resends with confirm_open_work', async () => {
    let calls = 0;
    const fake = api({
      routes: {
        ...COMMON,
        ...record(inProgress()),
        [`POST ${PATH}/actions/resolve`]: () => {
          calls += 1;
          return calls === 1
            ? {
                status: 409,
                body: problem(409, 'open_work_unconfirmed', {
                  params: { count: 2, items: 'Replace toner, Call vendor' },
                }),
              }
            : { body: resolvedItem() };
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-resolve'));
    await typeRichText('inc-resolution-editor', 'Fixed');
    fireEvent.click(screen.getByTestId('inc-reason-confirm'));
    const warning = await screen.findByTestId('inc-open-work');
    expect(warning.textContent).toContain('2 items of work are still open');
    expect(within(warning).getByTestId('inc-open-work-items').textContent).toBe(
      'Replace toner, Call vendor',
    );
    const confirm = screen.getByTestId('inc-reason-confirm');
    expect(confirm.textContent).toBe('Confirm and continue');
    fireEvent.click(confirm);
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/actions/resolve`)).toHaveLength(2);
    });
    const [first, second] = fake.find('POST', `${PATH}/actions/resolve`);
    expect(first?.body).toMatchObject({ confirm_open_work: false });
    expect(second?.body).toMatchObject({
      confirm_open_work: true,
      resolution: '<p dir="auto">Fixed</p>',
    });
  });

  it('REQ-INC-095: blocking open work is refused at the dialog, with the items', async () => {
    api({
      routes: {
        ...COMMON,
        ...record(inProgress()),
        [`POST ${PATH}/actions/resolve`]: {
          status: 409,
          body: problem(409, 'open_work_blocked', {
            params: { count: 1, items: 'Manager approval' },
          }),
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-resolve'));
    await typeRichText('inc-resolution-editor', 'Fixed');
    fireEvent.click(screen.getByTestId('inc-reason-confirm'));
    expect((await screen.findByTestId('form-problem')).textContent).toContain(
      'This cannot be done while this work is open: Manager approval.',
    );
  });
});

describe('Closing', () => {
  it('REQ-INC-093: close requires a closure code and sends it', async () => {
    const closed = fakeIncident({ status: 'closed', status_category: 'closed', version: 6 });
    const fake = api({
      routes: {
        ...COMMON,
        ...record(resolvedItem()),
        [`POST ${PATH}/actions/close`]: { body: closed },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-close'));
    fireEvent.click(await screen.findByTestId('inc-reason-confirm'));
    expect((await screen.findByTestId('inc-closure-code-error')).textContent).toBe(
      'Choose a closure code.',
    );
    expect(fake.find('POST', `${PATH}/actions/close`)).toHaveLength(0);
    fireEvent.mouseDown(selectorOf(screen.getByTestId('inc-closure-code')));
    fireEvent.click(await screen.findByTitle('Workaround given'));
    fireEvent.click(screen.getByTestId('inc-reason-confirm'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/actions/close`)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', `${PATH}/actions/close`);
    expect(sent?.body).toMatchObject({ closure_code: 'workaround', confirm_open_work: false });
    expect(sent?.headers.get('If-Match')).toBe('"5"');
  });

  it('REQ-INC-093: retired closure codes are not offered', async () => {
    const catalogue = fakeIncidentCatalogue();
    catalogue.closure_codes = catalogue.closure_codes.map((v) =>
      v.code === 'duplicate' ? { ...v, disabled: true } : v,
    );
    api({
      routes: {
        ...COMMON,
        'GET /api/v1/incidents/settings': { body: catalogue },
        ...record(resolvedItem()),
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-close'));
    fireEvent.mouseDown(selectorOf(await screen.findByTestId('inc-closure-code')));
    expect(await screen.findByTitle('Fixed')).toBeDefined();
    expect(screen.queryByTitle('Duplicate')).toBeNull();
  });
});

describe('The record', () => {
  it('REQ-INC-090/093: the record shows the resolution and the closure code in words', async () => {
    api({
      routes: {
        ...COMMON,
        ...record(
          fakeIncident({
            status: 'closed',
            status_category: 'closed',
            resolution: '<p>Restarted the <strong>mail relay</strong>.</p>',
            closure_code: 'no_fault_found',
          }),
        ),
      },
    });
    render(<App />);
    const resolution = await screen.findByTestId('inc-resolution');
    expect(resolution.innerHTML).toBe('<p>Restarted the <strong>mail relay</strong>.</p>');
    expect(resolution.getAttribute('dir')).toBe('auto');
    expect(screen.getByTestId('inc-closure-code-view').textContent).toBe(
      'Closure code: No fault found',
    );
  });

  it('REQ-INC-096: a resolved record says when it auto-closes, or that it waits until told', async () => {
    const catalogue = fakeIncidentCatalogue();
    catalogue.closure = { ...catalogue.closure, auto_close_days: 3, requester_channels: ['email'] };
    const told = { ...resolvedItem(), resolution: '<p>Done</p>' };
    api({
      routes: {
        ...COMMON,
        'GET /api/v1/incidents/settings': { body: catalogue },
        ...record(told),
      },
    });
    render(<App />);
    expect((await screen.findByTestId('inc-auto-close')).textContent).toBe(
      'Closes automatically only once the requester has been told of the resolution.',
    );
  });

  it('REQ-INC-098: a follow-up links to the incident it follows, by its ID', async () => {
    const earlier = fakeIncident({
      id: '01900000-0000-7000-8000-00000000c0aa',
      display_id: 'INC-3',
    });
    api({
      routes: {
        ...COMMON,
        ...record(fakeIncident({ follows_id: earlier.id })),
        [`GET /api/v1/incidents/${earlier.id}`]: { body: earlier },
      },
    });
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId('inc-follows').textContent).toBe('INC-3');
    });
    expect(screen.getByTestId('inc-follows').getAttribute('href')).toBe(`/incidents/${earlier.id}`);
  });
});

describe('A late reply', () => {
  it('REQ-INC-098: a reply that started a new incident says its ID', async () => {
    rememberTab(SESSION_USER, 'conversation');
    api({
      routes: {
        ...COMMON,
        ...record(fakeIncident({ status: 'closed', status_category: 'closed' })),
        [`POST ${PATH}/conversation`]: {
          status: 201,
          body: {
            entry: fakeConversationEntry(),
            not_notified: [],
            people: {},
            follow_up: { id: '01900000-0000-7000-8000-00000000c0bb', display_id: 'INC-12' },
          },
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('conv-add-note'));
    await typeRichText('conv-editor', 'It broke again');
    await waitFor(() => {
      expect(screen.getByTestId<HTMLButtonElement>('conv-send').disabled).toBe(false);
    });
    fireEvent.click(screen.getByTestId('conv-send'));
    expect(
      await screen.findByText(
        'This reply came after the reopen window, so it started a new incident: INC-12.',
      ),
    ).toBeDefined();
  });
});

describe('History', () => {
  const entry = (overrides: Record<string, unknown>) => ({
    change_id: 'c-9',
    version: 9,
    kind: 'status',
    occurred_at: '2026-10-28T09:00:00Z',
    actor_type: 'system',
    actor_id: null,
    actor_name: null,
    source: 'system',
    reason: null,
    automation: null,
    changes: [],
    ...overrides,
  });

  it('REQ-INC-096 AC3: an auto-close says why in words, with the closure code labelled', async () => {
    rememberTab(SESSION_USER, 'history');
    api({
      routes: {
        ...COMMON,
        ...record(fakeIncident()),
        [`GET ${PATH}/history`]: {
          body: {
            items: [
              entry({
                automation: { kind: 'auto_move', rule: 'auto_close', action: 'close' },
                changes: [
                  { field: 'status', old: 'resolved', new: 'closed' },
                  { field: 'closure_code', old: null, new: 'fixed' },
                  { field: 'resolution', old: null, new: '<p>x</p>' },
                ],
              }),
            ],
            next_cursor: null,
            people: {},
          },
        },
      },
    });
    render(<App />);
    expect((await screen.findByTestId('inc-history-why')).textContent).toBe(
      'Closed automatically: the requester was told of the resolution and did not answer in time.',
    );
    const text = screen.getByTestId('inc-history').textContent;
    expect(text).toContain('Closure code');
    expect(text).toContain('Fixed');
    expect(text).not.toContain('auto_close');
    expect(text).not.toContain('<p>');
  });

  it('REQ-INC-051/095/096: requester replies and confirmed open work read in words', async () => {
    rememberTab(SESSION_USER, 'history');
    api({
      routes: {
        ...COMMON,
        ...record(fakeIncident()),
        [`GET ${PATH}/history`]: {
          body: {
            items: [
              entry({
                change_id: 'c-1',
                automation: { kind: 'auto_move', rule: 'requester_reply', action: 'reopen' },
              }),
              entry({
                change_id: 'c-2',
                automation: { kind: 'auto_move', rule: 'requester_rejected', action: 'reopen' },
              }),
              entry({
                change_id: 'c-3',
                actor_type: 'user',
                actor_name: 'Tariq Technician',
                source: 'ui',
                changes: [
                  {
                    field: 'open_work_confirmed',
                    old: null,
                    new: ['Replace toner', 'Call vendor'],
                  },
                ],
              }),
            ],
            next_cursor: null,
            people: {},
          },
        },
      },
    });
    render(<App />);
    const whys = await screen.findAllByTestId('inc-history-why');
    expect(whys.map((w) => w.textContent)).toEqual([
      'The requester replied within the reopen window, so it was reopened.',
      'The requester said it is not fixed, so it was reopened.',
    ]);
    expect(screen.getByTestId('inc-history').textContent).toContain('Open work confirmed');
    expect(screen.getByTestId('inc-history').textContent).toContain('Replace toner, Call vendor');
  });
});

describe('Arabic', () => {
  it('REQ-INC-090: the resolve dialog is in Arabic, right to left', async () => {
    api({
      me: fakeSession({ locale: 'ar' }),
      routes: { ...COMMON, ...record(inProgress(['category_id'])) },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-resolve'));
    const missing = await screen.findByTestId('inc-closing-missing');
    expect(missing.textContent).toBe('املأ هذه في السجل أولًا: الفئة.');
    const dialog = screen.getByRole('dialog');
    expect(dialog.textContent).toContain('الحل');
    await waitFor(() => {
      expect(document.documentElement.dir).toBe('rtl');
    });
  });
});
