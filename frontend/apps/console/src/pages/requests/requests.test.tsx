import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { CatalogItem } from '@supportx/api-client';
import { fakeIncident } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-030 s1: service requests in the console: the list, raising one from the catalog, one record.

const ITEM_ID = '01a1a2b3-0000-7000-8000-00000000c001';
const SR_ID = '01a1a2b3-0000-7000-8000-00000000c501';

const laptop: CatalogItem = {
  id: ITEM_ID,
  names: { en: 'New laptop', ar: 'حاسوب جديد' },
  summaries: {},
  descriptions: {},
  keywords: {},
  icon: null,
  category_id: null,
  extra_category_ids: [],
  kind: 'service',
  template_id: null,
  audience: 'everyone',
  status: 'published',
  enabled: true,
  publish_at: null,
  retire_at: null,
  published_at: null,
  owner_id: null,
  featured: false,
  sort_order: 0,
  subject_template: null,
  requesters_see_approval: true,
  starter: false,
  missing_translations: [],
  questions: [
    {
      key: 'model',
      label: { en: 'Model' },
      kind: 'choice',
      required: true,
      options: ['air', 'pro'],
    },
  ],
  approval: {
    approvers: [{ kind: 'requested_for_manager', person_id: null }],
    comments_required: false,
    self_approval: false,
  },
  plan: [],
  default_priority: 'p2',
  requester_sets_priority: false,
  sla_policy_id: null,
  group_id: null,
  technician_id: null,
  technician_after_approval: false,
  count_approval_time: false,
  auto_fulfil: true,
  can_manage: true,
  version: 1,
};

const request = fakeIncident({
  id: SR_ID,
  display_id: 'SR-1',
  subject: 'Laptop for Sara',
  status: 'awaiting_approval',
  catalog_item_id: ITEM_ID,
  answers: { model: 'air' },
  approval_status: 'pending',
  priority: 'p2',
  priority_source: 'catalog_item',
});

const APPROVAL_ID = '01a1a2b3-0000-7000-8000-00000000a001';
const MANAGER = '01a1a2b3-0000-7000-8000-00000000b001';
const pendingApproval = {
  id: APPROVAL_ID,
  stage: 1,
  approver_id: MANAGER,
  origin: 'manager',
  route_reason: null,
  state: 'pending',
  decided_at: null,
  decided_by: null,
  channel: null,
  comment: null,
  comment_private: false,
  comments_required: false,
  self_approved: false,
  can_decide: true,
  created_at: '2026-11-04T08:00:00Z',
  version: 1,
};
const approvalsBody = {
  items: [pendingApproval],
  people: { [MANAGER]: { display_name: 'Omar Manager', email: 'omar@example.com' } },
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function api(routes: Record<string, unknown> = {}) {
  const fake = consoleApi({
    routes: {
      'GET /api/v1/catalog/items': { body: [laptop] },
      [`GET /api/v1/catalog/items/${ITEM_ID}`]: { body: laptop },
      'GET /api/v1/service-requests': {
        body: {
          items: [{ ...request, catalog_item_id: ITEM_ID, approval_status: 'pending' }],
          next_cursor: null,
          has_more: false,
          people: {},
        },
      },
      'GET /api/v1/service-requests/views': {
        body: [
          { view: 'pending_approval', count: 1, capped: false },
          { view: 'awaiting_fulfilment', count: 0, capped: false },
        ],
      },
      [`GET /api/v1/service-requests/${SR_ID}`]: { body: request },
      [`GET /api/v1/service-requests/${SR_ID}/approvals`]: { body: approvalsBody },
      [`GET /api/v1/service-requests/${SR_ID}/tasks`]: { body: { items: [], done: 0, total: 0 } },
      ...routes,
    },
  });
  restore = fake.restore;
  return fake;
}

describe('console: service requests', () => {
  it('lists requests with their item and approval status', async () => {
    window.history.pushState({}, '', '/requests');
    api();
    render(<App />);
    const row = (await screen.findByTestId('sr-row-SR-1')).closest('tr');
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText('New laptop')).toBeDefined();
    // the status and the approval status both read it while it waits
    expect(within(row as HTMLElement).getAllByText('Awaiting approval')).toHaveLength(2);
  });

  it('narrows the list to an approval view, with its count', async () => {
    window.history.pushState({}, '', '/requests');
    const fake = api();
    render(<App />);
    await screen.findByTestId('sr-row-SR-1');
    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'View' }));
    fireEvent.click(await screen.findByTitle('Pending approval (1)'));
    await waitFor(() => {
      const asked = fake.find('GET', '/api/v1/service-requests');
      expect(asked.some((r) => r.url.searchParams.get('view') === 'pending_approval')).toBe(true);
    });
  });

  it('raises one from the catalog with the form’s answers, once', async () => {
    window.history.pushState({}, '', '/requests/new');
    const fake = api({ 'POST /api/v1/service-requests': { status: 201, body: request } });
    render(<App />);
    fireEvent.click(await screen.findByTestId(`sr-item-${ITEM_ID}`));
    fireEvent.change(await screen.findByTestId('sr-subject'), {
      target: { value: ' Laptop for Sara ' },
    });
    // Up to four choices show as radio buttons (WP-031's question renderer).
    fireEvent.click(screen.getByRole('radio', { name: 'air' }));
    fireEvent.click(screen.getByTestId('sr-send'));
    await waitFor(() => {
      expect(window.location.pathname).toBe(`/requests/${SR_ID}`);
    });
    const [sent] = fake.find('POST', '/api/v1/service-requests');
    expect(sent?.body).toMatchObject({
      subject: 'Laptop for Sara',
      catalog_item_id: ITEM_ID,
      answers: { model: 'air' },
    });
    expect(sent?.headers.get('Idempotency-Key')).toBeTruthy();
  });

  it('shows one request with its item details and approval status', async () => {
    window.history.pushState({}, '', `/requests/${SR_ID}`);
    api();
    render(<App />);
    // One status chip; the pending approval is not said twice (UI pass 3, Haider).
    expect((await screen.findByTestId('sr-status')).textContent).toBe('Awaiting approval');
    expect(screen.queryByTestId('sr-approval')).toBeNull();
    fireEvent.click(await screen.findByTestId('sr-tab-details'));
    const answers = await screen.findByTestId('sr-answers');
    await waitFor(() => {
      expect(within(answers).getByText('air')).toBeDefined();
    });
  });

  it('shows the approvals and the approver approves with If-Match', async () => {
    window.history.pushState({}, '', `/requests/${SR_ID}`);
    const fake = api({
      [`POST /api/v1/service-requests/${SR_ID}/approvals/${APPROVAL_ID}/decision`]: {
        body: { ...pendingApproval, state: 'approved', can_decide: false, version: 2 },
      },
    });
    render(<App />);
    const entry = await screen.findByTestId(`sr-approval-${APPROVAL_ID}`);
    expect(within(entry).getByText('Omar Manager')).toBeDefined();
    expect(within(entry).getByTestId('approval-state').textContent).toBe('Waiting');
    fireEvent.click(within(entry).getByTestId('approval-approve'));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve' }));
    await waitFor(() => {
      expect(
        fake.find('POST', `/api/v1/service-requests/${SR_ID}/approvals/${APPROVAL_ID}/decision`),
      ).toHaveLength(1);
    });
    const [sent] = fake.find(
      'POST',
      `/api/v1/service-requests/${SR_ID}/approvals/${APPROVAL_ID}/decision`,
    );
    expect(sent?.body).toEqual({ decision: 'approve', comment: null, private: false });
    expect(sent?.headers.get('If-Match')).toBe('"1"');
  });

  it('a rejection cannot be sent without a reason', async () => {
    window.history.pushState({}, '', `/requests/${SR_ID}`);
    api();
    render(<App />);
    const entry = await screen.findByTestId(`sr-approval-${APPROVAL_ID}`);
    fireEvent.click(within(entry).getByTestId('approval-reject'));
    const dialog = await screen.findByRole('dialog');
    const send = within(dialog).getByRole('button', { name: 'Reject' });
    expect((send as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(within(dialog).getByTestId('approval-comment'), {
      target: { value: 'Not in budget' },
    });
    expect((send as HTMLButtonElement).disabled).toBe(false);
  });

  it('the header drawer lists the approvals waiting for me', async () => {
    window.history.pushState({}, '', '/requests');
    api({
      'GET /api/v1/service-requests/my-approvals': {
        body: {
          items: [
            {
              approval_id: APPROVAL_ID,
              approval_version: 1,
              record_id: SR_ID,
              display_id: 'SR-1',
              subject: 'Laptop for Sara',
              requester_id: MANAGER,
              on_behalf_of_id: null,
              catalog_item_id: ITEM_ID,
              comments_required: false,
              created_at: '2026-11-04T08:00:00Z',
            },
          ],
          people: { [MANAGER]: { display_name: 'Omar Manager', email: 'omar@example.com' } },
        },
      },
    });
    render(<App />);
    const opener = await screen.findByRole('button', { name: '1 approval waiting for you' });
    fireEvent.click(opener);
    const row = await screen.findByTestId('my-approval-SR-1');
    expect(within(row).getByText('For Omar Manager', { exact: false })).toBeDefined();
  });

  it('ticks a fulfilment task done with If-Match', async () => {
    window.history.pushState({}, '', `/requests/${SR_ID}`);
    const task = {
      id: '01a1a2b3-0000-7000-8000-00000000d001',
      work_item_id: SR_ID,
      title: 'Order the laptop',
      description: null,
      owner_id: null,
      group_id: null,
      status: 'open',
      priority: 'normal',
      due_at: null,
      done_at: null,
      position: 0,
      from_plan: true,
      required: true,
      internal: false,
      version: 2,
      created_at: '2026-11-04T08:00:00Z',
      updated_at: '2026-11-04T08:00:00Z',
    };
    const path = `/api/v1/service-requests/${SR_ID}/tasks/${task.id}`;
    const fake = api({
      [`GET /api/v1/service-requests/${SR_ID}/tasks`]: {
        body: { items: [task], done: 0, total: 1 },
      },
      [`PATCH ${path}`]: { body: { ...task, status: 'done', version: 3 } },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('sr-tab-tasks')); // fulfilment is a tab (template A)
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Order the laptop' }));
    await waitFor(() => {
      expect(fake.find('PATCH', path)).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', path);
    expect(sent?.body).toEqual({ status: 'done' });
    expect(sent?.headers.get('If-Match')).toBe('"2"');
  });
});

describe('console: the service request record (template A)', () => {
  it("shows the requester and the conversation from the request's own routes", async () => {
    window.history.pushState({}, '', `/requests/${SR_ID}`);
    const fulfilled = { ...request, status: 'in_progress', approval_status: 'approved' };
    const fake = api({
      [`GET /api/v1/service-requests/${SR_ID}`]: { body: fulfilled },
      [`GET /api/v1/service-requests/${SR_ID}/conversation`]: {
        body: { items: [], people: {}, next_cursor: null },
      },
    });
    render(<App />);
    expect((await screen.findByTestId('sr-status')).textContent).toBe('In progress');
    // A decided approval adds its words in the panel; the requester is there too.
    expect((await screen.findByTestId('sr-approval')).textContent).toBe('Approved');
    expect(screen.getByTestId('sr-panel').textContent).toContain('Requester');
    await waitFor(() => {
      expect(fake.find('GET', `/api/v1/service-requests/${SR_ID}/conversation`)).toHaveLength(1);
    });
    expect(fake.find('GET', `/api/v1/incidents/${SR_ID}/conversation`)).toHaveLength(0);
  });
});
