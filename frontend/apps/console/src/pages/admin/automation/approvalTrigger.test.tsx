import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-047a S4 (REQ-SR-044): a trigger may ask for an approval where the type's approvals can be
// decided. No admin screen lists service request triggers yet, so the automation page here
// shows the triggers of the type named in the address.
vi.mock('./AutomationPage', async () => {
  const { TriggersTab } = await import('./TriggersTab');
  return {
    AutomationPage: () => (
      <TriggersTab
        recordType={new URLSearchParams(window.location.search).get('type') ?? 'incident'}
      />
    ),
  };
});

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const GROUP_ID = '01a1a2b3-0000-7000-8000-0000000f0201';

let restore: () => void = () => undefined;
function api() {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/access-settings': {
        body: { technician_scope: 'group', answered_at: '2026-10-27T08:00:00Z', version: 1 },
      },
      'GET /api/v1/automation/fields': {
        body: [
          { name: 'priority', kind: 'code', values: ['p1', 'p2'], settable: true, derived: false },
        ],
      },
      'GET /api/v1/automation/triggers': { body: [] },
      // The offer is the server's (lane C's #627 review): only an approvable type may ask.
      'GET /api/v1/automation/trigger-events': (call) => ({
        body: {
          offered: ['created', 'updated'],
          offered_actions:
            call.url.searchParams.get('record_type') === 'service_request'
              ? ['set', 'note', 'start_workflow', 'start_approval']
              : ['set', 'note'],
        },
      }),
      'GET /api/v1/automation/workflows/node-types': {
        body: [
          {
            type: 'approval',
            category: 'people',
            available: true,
            why_not: null,
            outputs: ['approved', 'rejected'],
            optional: [],
            roles: ['requester'],
          },
        ],
      },
      'GET /api/v1/organization/groups': {
        body: [{ id: GROUP_ID, name: 'Network', kind: 'group' }],
      },
      'GET /api/v1/users': { body: { items: [], has_more: false, next_cursor: null } },
      'POST /api/v1/automation/triggers': { body: {} },
    },
  });
  restore = fake.restore;
  return fake;
}

async function pick(testId: string, option: string) {
  const select = await screen.findByTestId(testId);
  fireEvent.mouseDown(
    select.closest('.ant-select')?.querySelector('.ant-select-selector') ?? select,
  );
  const last = (await screen.findAllByTitle(option)).at(-1);
  if (last === undefined) throw new Error(`no option ${option}`);
  fireEvent.click(last);
}

async function kindOptions(): Promise<string[]> {
  fireEvent.click(await screen.findByTestId('trigger-add'));
  const kind = await screen.findByTestId('trigger-action-0-kind');
  fireEvent.mouseDown(kind.querySelector('.ant-select-selector') ?? kind);
  await screen.findAllByTitle('Add a private note');
  return Array.from(document.querySelectorAll('.ant-select-item-option')).map((n) => n.textContent);
}

afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

describe('Admin › Triggers › Ask for an approval (WP-047a S4)', () => {
  beforeEach(() => {
    setDefaultClientFactory(inertClientFactory);
  });

  it('a service request trigger asks named approvers, and saving sends them and the rule', async () => {
    const fake = api();
    window.history.pushState({}, '', '/admin/automation/triggers?type=service_request');
    render(<App />);
    expect(await kindOptions()).toContain('Ask for an approval');
    const ask = (await screen.findAllByTitle('Ask for an approval')).at(-1);
    if (ask === undefined) throw new Error('no option');
    fireEvent.click(ask);
    const approval = await screen.findByTestId('trigger-action-0-approval');
    await pick('approval-roles', 'Requester');
    await pick('approval-groups', 'Network');
    fireEvent.click(within(approval).getByLabelText('Every approver'));
    // A trigger's ask has no timeout: that belongs to a workflow's approval step.
    expect(within(approval).queryByLabelText('Timeout (hours)')).toBeNull();
    fireEvent.change(screen.getByTestId('trigger-name'), { target: { value: 'Ask the team' } });
    fireEvent.click(screen.getByTestId('trigger-save'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/automation/triggers')).toHaveLength(1);
    });
    const body = fake.find('POST', '/api/v1/automation/triggers')[0]?.body as {
      record_type: string;
      actions: unknown[];
    };
    expect(body.record_type).toBe('service_request');
    expect(body.actions).toEqual([
      expect.objectContaining({
        kind: 'start_approval',
        approvers: { user_ids: [], group_ids: [GROUP_ID], roles: ['requester'] },
        rule: 'all',
      }),
    ]);
  });

  it('an incident trigger does not offer it', async () => {
    api();
    window.history.pushState({}, '', '/admin/automation/triggers?type=incident');
    render(<App />);
    const options = await kindOptions();
    expect(options).toContain('Add a private note');
    expect(options).not.toContain('Ask for an approval');
  });
});
