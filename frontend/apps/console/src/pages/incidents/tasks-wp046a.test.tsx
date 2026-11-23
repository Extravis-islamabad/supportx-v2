import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';
import { rememberTab } from './tabs';

// WP-046a S1 (REQ-INC-073..076): task details, dependencies, templates and My tasks.

const SESSION_USER = '01900000-0000-7000-8000-000000000101';
const ITEM = fakeIncident();
const PATH = `/api/v1/incidents/${ITEM.id}`;
const FIRST = '01900000-0000-7000-8000-00000000a001';
const SECOND = '01900000-0000-7000-8000-00000000a002';

let restore: () => void = () => undefined;
function api(routes: Record<string, unknown>) {
  const fake = consoleApi({
    routes: {
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/incidents/categories': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/organization/sites': { body: [] },
      [`GET ${PATH}`]: { body: ITEM, headers: { ETag: '"1"' } },
      [`GET ${PATH}/worklogs`]: { body: { items: [], minutes: 0, by_owner: [], by_type: [] } },
      [`GET ${PATH}/links`]: { body: [] },
      ...routes,
    } as Parameters<typeof consoleApi>[0] extends { routes?: infer R } | undefined ? R : never,
  });
  restore = fake.restore;
  return fake;
}

function task(id: string, title: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    work_item_id: ITEM.id,
    title,
    description: null,
    owner_id: null,
    group_id: null,
    status: 'open',
    priority: 'normal',
    due_at: null,
    done_at: null,
    position: 0,
    depends_on: [],
    blocked_by: [],
    overdue: false,
    extra_cost: null,
    version: 1,
    created_at: '2026-11-10T10:00:00Z',
    updated_at: '2026-11-10T10:00:00Z',
    ...extra,
  };
}

const TASKS = {
  items: [
    task(FIRST, 'Back up the switch', { overdue: true, due_at: '2026-11-01T10:00:00Z' }),
    task(SECOND, 'Upgrade the firmware', { depends_on: [FIRST], blocked_by: [FIRST] }),
  ],
  done: 0,
  total: 2,
};

describe('Tasks (WP-046a S1)', () => {
  afterEach(() => {
    restore();
  });

  it('REQ-INC-075/076: a waiting task names what it waits for; an overdue one says so', async () => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    rememberTab(SESSION_USER, 'tasks');
    api({
      [`GET ${PATH}/tasks`]: { body: TASKS },
      'GET /api/v1/incidents/task-templates': { body: [] },
    });
    render(<App />);
    expect((await screen.findByTestId('inc-task-blocked-1')).textContent).toBe(
      'Waits for Back up the switch',
    );
    expect(screen.getByTestId('inc-task-overdue-0').textContent).toBe('Overdue');
  });

  it('REQ-INC-074: a task template is added to the record', async () => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    rememberTab(SESSION_USER, 'tasks');
    const template = {
      id: '01900000-0000-7000-8000-00000000b001',
      name: 'Laptop set-up',
      description: null,
      tasks: [{ title: 'Image it', priority: 'normal' }],
      disabled: false,
      version: 1,
    };
    const fake = api({
      [`GET ${PATH}/tasks`]: { body: TASKS },
      'GET /api/v1/incidents/task-templates': { body: [template] },
      [`POST ${PATH}/tasks/from-template`]: { status: 201, body: TASKS },
    });
    render(<App />);
    const picker = await screen.findByTestId('inc-task-from-template');
    fireEvent.mouseDown(within(picker).getByRole('combobox'));
    fireEvent.click(await screen.findByText('Laptop set-up'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/tasks/from-template`)).toHaveLength(1);
    });
    expect(fake.find('POST', `${PATH}/tasks/from-template`)[0]?.body).toEqual({
      template_id: template.id,
    });
  });

  it('REQ-INC-075 AC3: what a task waits for is set from its details', async () => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    rememberTab(SESSION_USER, 'tasks');
    const fake = api({
      [`GET ${PATH}/tasks`]: { body: TASKS },
      'GET /api/v1/incidents/task-templates': { body: [] },
      [`PATCH ${PATH}/tasks/${FIRST}`]: { body: TASKS.items[0] },
      [`PUT ${PATH}/tasks/${FIRST}/dependencies`]: { body: TASKS },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-task-details-0'));
    const drawer = await screen.findByTestId('task-details');
    fireEvent.mouseDown(within(drawer).getByRole('combobox'));
    fireEvent.click(await screen.findByTitle('Upgrade the firmware'));
    fireEvent.click(screen.getByTestId('task-details-save'));
    await waitFor(() => {
      expect(fake.find('PUT', `${PATH}/tasks/${FIRST}/dependencies`)).toHaveLength(1);
    });
    expect(fake.find('PUT', `${PATH}/tasks/${FIRST}/dependencies`)[0]?.body).toEqual({
      depends_on: [SECOND],
    });
  });

  it('REQ-INC-076: My tasks lists tasks on every type and links each record', async () => {
    window.history.pushState({}, '', '/my-tasks');
    api({
      'GET /api/v1/my-tasks': {
        body: [
          {
            task: task(FIRST, 'Check the backup', { overdue: true }),
            work_item_id: '01900000-0000-7000-8000-00000000c001',
            display_id: 'CHG-4',
            subject: 'Core switch firmware',
            record_type: 'change',
          },
        ],
      },
    });
    render(<App />);
    const row = await screen.findByTestId(`my-task-${FIRST}`);
    expect(within(row).getByRole('link').getAttribute('href')).toBe(
      '/changes/01900000-0000-7000-8000-00000000c001',
    );
    expect(within(row).getByTestId(`my-task-overdue-${FIRST}`)).toBeDefined();
  });
});
