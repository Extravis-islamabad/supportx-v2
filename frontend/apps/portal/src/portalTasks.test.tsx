import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeApi, fakeEntitlements, fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from './App';

// WP-047a S5 (REQ-SR-049, -050): a manager outside the desk works the one task a plan gave them.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const ME = fakeSession({ user_type: 'requester', roles: ['requester'] });
const TASK = {
  id: '01900000-0000-7000-8000-00000000e501',
  work_item_id: '01900000-0000-7000-8000-00000000e001',
  request_ref: 'SR-17',
  title: 'Manager sign-off',
  status: 'open',
  kind: 'task',
  fields: [{ key: 'cost_centre', label: { en: 'Cost centre' }, kind: 'text', required: true }],
  field_values: {},
  due_at: null,
  version: 3,
};
const GONE = {
  status: 404,
  body: {
    type: 'about:blank',
    title: 'Not Found',
    status: 404,
    code: 'work_item_task_not_found',
    message_key: 'errors.work_item_task_not_found',
    params: {},
    errors: [],
  },
};

function portal(routes: Record<string, unknown>) {
  const fake = fakeApi({
    'GET /api/v1/auth/me': { body: ME },
    'GET /api/v1/entitlements': { body: fakeEntitlements() },
    'GET /api/v1/announcements/feed': { body: { items: [], next_change_in_seconds: null } },
    ...routes,
  });
  restore = fake.restore;
  return fake;
}

describe('portal: your tasks', () => {
  it('lists the task with its request reference only, and a new one shows live', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', '/tasks');
    let rows: unknown[] = [];
    portal({ 'GET /api/v1/portal/tasks': () => ({ body: { items: rows } }) });
    render(<App />);
    expect(await screen.findByText('No tasks for you right now.')).toBeTruthy();
    rows = [TASK];
    act(() => {
      realtime.publish(`:user:${ME.user.id}`, {
        type: 'work_items.my_tasks_changed',
        ids: [TASK.id],
      });
    });
    const row = await screen.findByTestId(`portal-task-${TASK.id}`);
    expect(row.textContent).toContain('Manager sign-off');
    expect(row.textContent).toContain('For request SR-17');
  });

  it('completing waits for the required field, then sends it with the values', async () => {
    window.history.pushState({}, '', `/tasks/${TASK.id}`);
    const fake = portal({
      [`GET /api/v1/portal/tasks/${TASK.id}`]: { body: TASK },
      [`PATCH /api/v1/portal/tasks/${TASK.id}`]: {
        body: { ...TASK, status: 'done', field_values: { cost_centre: 'CC-9' }, version: 4 },
      },
      'GET /api/v1/portal/tasks': { body: { items: [] } },
    });
    render(<App />);
    const done = await screen.findByTestId('portal-task-done');
    expect(done.hasAttribute('disabled')).toBe(true);
    expect(screen.getByText('Fill in the required fields to complete it.')).toBeTruthy();
    fireEvent.change(screen.getByTestId('sr-q-cost_centre'), { target: { value: 'CC-9' } });
    await waitFor(() => {
      expect(screen.getByTestId('portal-task-done').hasAttribute('disabled')).toBe(false);
    });
    fireEvent.click(screen.getByTestId('portal-task-done'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/portal/tasks/${TASK.id}`)).toHaveLength(1);
    });
    const [call] = fake.find('PATCH', `/api/v1/portal/tasks/${TASK.id}`);
    expect(call?.body).toEqual({ status: 'done', field_values: { cost_centre: 'CC-9' } });
    expect(call?.headers.get('If-Match')).toBe('"3"');
  });

  it('a task no longer mine says so and shows nothing of it', async () => {
    window.history.pushState({}, '', `/tasks/${TASK.id}`);
    portal({ [`GET /api/v1/portal/tasks/${TASK.id}`]: GONE });
    render(<App />);
    expect(
      await screen.findByText('This task is no longer yours, or it is already closed.'),
    ).toBeTruthy();
    expect(screen.queryByText('Manager sign-off')).toBeNull();
  });

  it('a server failure is reported, never read as "no longer yours"', async () => {
    window.history.pushState({}, '', `/tasks/${TASK.id}`);
    const fake = portal({
      [`GET /api/v1/portal/tasks/${TASK.id}`]: {
        status: 500,
        body: {
          ...GONE.body,
          status: 500,
          code: 'internal_error',
          message_key: 'errors.internal_error',
        },
      },
    });
    render(<App />);
    await waitFor(() => {
      expect(fake.find('GET', `/api/v1/portal/tasks/${TASK.id}`).length).toBeGreaterThan(0);
    });
    await new Promise((resolve) => setTimeout(resolve, 50)); // the failed fetch settles
    expect(screen.queryByText('This task is no longer yours, or it is already closed.')).toBeNull();
  });

  it('a hand-over task is completed by the desk, never from the portal', async () => {
    window.history.pushState({}, '', `/tasks/${TASK.id}`);
    portal({
      [`GET /api/v1/portal/tasks/${TASK.id}`]: {
        body: { ...TASK, kind: 'asset_handover', fields: [] },
      },
    });
    render(<App />);
    expect(
      await screen.findByText('The service desk completes this task when it hands the asset over.'),
    ).toBeTruthy();
    expect(screen.getByTestId('portal-task-done').hasAttribute('disabled')).toBe(true);
  });
});
