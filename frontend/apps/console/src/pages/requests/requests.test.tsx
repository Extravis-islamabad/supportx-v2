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
  descriptions: {},
  category_id: null,
  audience: 'everyone',
  enabled: true,
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
      [`GET /api/v1/service-requests/${SR_ID}`]: { body: request },
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

  it('raises one from the catalog with the form’s answers, once', async () => {
    window.history.pushState({}, '', '/requests/new');
    const fake = api({ 'POST /api/v1/service-requests': { status: 201, body: request } });
    render(<App />);
    fireEvent.click(await screen.findByTestId(`sr-item-${ITEM_ID}`));
    fireEvent.change(await screen.findByTestId('sr-subject'), {
      target: { value: ' Laptop for Sara ' },
    });
    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Model' }));
    fireEvent.click(await screen.findByTitle('air'));
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
    expect((await screen.findByTestId('sr-approval')).textContent).toBe('Awaiting approval');
    const answers = await screen.findByTestId('sr-answers');
    await waitFor(() => {
      expect(within(answers).getByText('air')).toBeDefined();
    });
  });
});
