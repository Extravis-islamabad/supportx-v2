import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';
import { rememberTab } from './tabs';

// WP-020e: tasks, worklogs and links on the record. Test names cite parity file 01 criteria.

const SESSION_USER = '01900000-0000-7000-8000-000000000101';
const ITEM = fakeIncident();
const PATH = `/api/v1/incidents/${ITEM.id}`;

let restore: () => void = () => undefined;
function api(routes: Record<string, unknown>) {
  const fake = consoleApi({
    routes: {
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/incidents/categories': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/organization/sites': { body: [] },
      [`GET ${PATH}`]: { body: ITEM, headers: { ETag: '"1"' } },
      [`GET ${PATH}/tasks`]: { body: { items: [], done: 0, total: 0 } },
      [`GET ${PATH}/worklogs`]: { body: { items: [], minutes: 0, by_owner: [], by_type: [] } },
      [`GET ${PATH}/links`]: { body: [] },
      ...routes,
    } as Parameters<typeof consoleApi>[0] extends { routes?: infer R } | undefined ? R : never,
  });
  restore = fake.restore;
  return fake;
}

function task(title: string, status: string, position: number) {
  return {
    id: `01900000-0000-7000-8000-00000000a00${String(position)}`,
    work_item_id: ITEM.id,
    title,
    description: null,
    owner_id: null,
    group_id: null,
    status,
    priority: 'normal',
    due_at: null,
    done_at: null,
    position,
    version: 1,
    created_at: '2026-10-28T10:00:00Z',
    updated_at: '2026-10-28T10:00:00Z',
  };
}

describe('Incident parts (WP-020e)', () => {
  afterEach(() => {
    restore();
  });

  it('REQ-INC-072 AC1: the tasks tab says done over total; a task is added', async () => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    rememberTab(SESSION_USER, 'tasks');
    const fake = api({
      [`GET ${PATH}/tasks`]: {
        body: {
          items: [task('Check cable', 'done', 0), task('Swap printer', 'open', 1)],
          done: 1,
          total: 2,
        },
      },
      [`POST ${PATH}/tasks`]: { status: 201, body: task('Order toner', 'open', 2) },
    });
    render(<App />);
    expect((await screen.findByTestId('inc-tab-tasks')).textContent).toBe('Tasks 1/2');
    expect(screen.getByTestId('inc-tasks-count').textContent).toBe('Done: 1 of 2');
    fireEvent.change(screen.getByTestId('inc-task-title'), { target: { value: 'Order toner' } });
    fireEvent.click(screen.getByTestId('inc-task-add'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/tasks`)).toHaveLength(1);
    });
    expect(fake.find('POST', `${PATH}/tasks`)[0]?.body).toMatchObject({
      title: 'Order toner',
      status: 'open',
    });
  });

  it('REQ-INC-072: what is typed while a task saves is kept (found by the e2e in CI)', async () => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    rememberTab(SESSION_USER, 'tasks');
    let finish: () => void = () => undefined;
    const fake = api({
      [`GET ${PATH}/tasks`]: { body: { items: [], done: 0, total: 0 } },
      [`POST ${PATH}/tasks`]: async () => {
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
        return { status: 201, body: task('First', 'open', 0) };
      },
    });
    render(<App />);
    const title = await screen.findByTestId<HTMLInputElement>('inc-task-title');
    fireEvent.change(title, { target: { value: 'First' } });
    fireEvent.click(screen.getByTestId('inc-task-add'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/tasks`)).toHaveLength(1);
    });
    fireEvent.change(title, { target: { value: 'Second' } });
    await act(async () => {
      finish();
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    await waitFor(() => {
      expect(screen.getByTestId<HTMLButtonElement>('inc-task-add').disabled).toBe(false);
    });
    expect(title.value).toBe('Second');
  });

  it('REQ-INC-067: no worklog is saved without a start and an end or a duration', async () => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    rememberTab(SESSION_USER, 'worklogs');
    api({});
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-worklog-open'));
    const form = await screen.findByTestId('inc-worklog-form');
    expect(within(form).getByTestId<HTMLButtonElement>('inc-worklog-add').disabled).toBe(true);
    // Disabled only with the reason beside it (Haider, 2026-11-10).
    expect(within(form).getByTestId('inc-worklog-why').textContent).not.toBe('');
  });

  it('Haider 2026-11-10: the worklog footer is Cancel then Log time; Cancel clears and closes', async () => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    rememberTab(SESSION_USER, 'worklogs');
    api({});
    render(<App />);
    expect(screen.queryByTestId('inc-worklog-form')).toBeNull(); // closed until asked for
    fireEvent.click(await screen.findByTestId('inc-worklog-open'));
    const form = await screen.findByTestId('inc-worklog-form');
    const buttons = [...form.querySelectorAll('button')].map((b) => b.getAttribute('data-testid'));
    expect(buttons.slice(-2)).toEqual(['inc-worklog-cancel', 'inc-worklog-add']);
    expect(form.querySelectorAll('[data-testid="time-zone-note"]')).toHaveLength(1); // one note
    fireEvent.change(within(form).getByRole('textbox', { name: 'What was done' }), {
      target: { value: 'Swapped the toner' },
    });
    fireEvent.click(within(form).getByTestId('inc-worklog-cancel'));
    expect(screen.queryByTestId('inc-worklog-form')).toBeNull();
    fireEvent.click(screen.getByTestId('inc-worklog-open'));
    const reopened = await screen.findByTestId('inc-worklog-form');
    expect(
      within(reopened).getByRole<HTMLTextAreaElement>('textbox', { name: 'What was done' }).value,
    ).toBe(''); // cleared, not kept
  });

  it('REQ-INC-084 AC3: a link to a record you cannot see shows without its ID or subject', async () => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    rememberTab(SESSION_USER, 'links');
    api({
      [`GET ${PATH}/links`]: {
        body: [
          {
            id: 'l1',
            kind: 'related',
            relation: 'related',
            other_id: null,
            other_display_id: null,
            other_subject: null,
            comment: null,
            version: 1,
            created_at: '2026-10-28T10:00:00Z',
          },
          {
            id: 'l2',
            kind: 'follows',
            relation: 'followed_by',
            other_id: '01900000-0000-7000-8000-0000000009f9',
            other_display_id: 'INC-9',
            other_subject: 'Printer again',
            comment: 'Same printer',
            version: 1,
            created_at: '2026-10-28T10:00:00Z',
          },
        ],
      },
    });
    render(<App />);
    const hidden = await screen.findByTestId('inc-link-hidden');
    expect(hidden.textContent).toContain('An incident you cannot see');
    expect(hidden.textContent).toContain('Related to');
    const shown = screen.getByTestId('inc-link-INC-9');
    expect(shown.textContent).toContain('Followed by');
    expect(shown.textContent).toContain('INC-9 · Printer again');
    expect(shown.textContent).toContain('Same printer');
  });

  it('QA10-P1-03: a cause has no delete (it is unlinked in its own place); a related link has one', async () => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    rememberTab(SESSION_USER, 'links');
    api({
      [`GET ${PATH}/links`]: {
        body: [
          {
            id: 'l3',
            kind: 'caused_by',
            relation: 'caused_by',
            other_id: '01900000-0000-7000-8000-0000000009f4',
            other_display_id: 'PRB-4',
            other_subject: 'VPN drops',
            comment: null,
            version: 1,
            created_at: '2026-10-28T10:00:00Z',
          },
          {
            id: 'l4',
            kind: 'related',
            relation: 'related',
            other_id: '01900000-0000-7000-8000-0000000009f8',
            other_display_id: 'INC-8',
            other_subject: 'Printer',
            comment: null,
            version: 1,
            created_at: '2026-10-28T10:00:00Z',
          },
        ],
      },
    });
    render(<App />);
    expect(await screen.findByTestId('inc-link-PRB-4')).toBeDefined();
    expect(screen.queryByTestId('inc-link-delete-PRB-4')).toBeNull();
    expect(screen.getByTestId('inc-link-delete-INC-8')).toBeDefined();
  });
});
