import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { CatalogItem, Feature } from '@supportx/api-client';
import { fakeApi, fakeEntitlements, fakeSession } from '@supportx/api-client/testing';

import { App } from './App';

// WP-047a S1: quantity (REQ-SR-014, Professional), needed-by and the expected date (REQ-SR-015),
// "request again" (REQ-SR-016) and the subject from the item's template, in the portal.

const CAT = '01a1a2b3-0000-7000-8000-00000000ca71';
const ITEM = '01a1a2b3-0000-7000-8000-00000000c171';
const SR = '01a1a2b3-0000-7000-8000-00000000c571';
const session = fakeSession({ user_type: 'requester', roles: ['requester'] });

const item: CatalogItem = {
  id: ITEM,
  kind: 'service',
  names: { en: 'Monitor' },
  summaries: {},
  descriptions: {},
  keywords: {},
  icon: null,
  category_id: CAT,
  extra_category_ids: [],
  template_id: null,
  audience: 'everyone',
  status: 'published',
  enabled: true,
  publish_at: null,
  retire_at: null,
  published_at: '2026-11-04T08:00:00Z',
  owner_id: null,
  featured: true,
  sort_order: 0,
  subject_template: null,
  requesters_see_approval: true,
  price_period: 'once',
  charge_to: 'requested_for_department',
  starter: false,
  questions: [
    {
      key: 'size',
      restarts_approval: false,
      label: { en: 'Size' },
      kind: 'text',
      required: true,
      options: [],
      option_labels: {},
      help: {},
      default: null,
      shown_to: ['requester', 'technician', 'approver'],
    },
  ],
  approval: null,
  plan: [],
  default_priority: 'p3',
  requester_sets_priority: false,
  sla_policy_id: null,
  group_id: null,
  technician_id: null,
  technician_after_approval: false,
  count_approval_time: false,
  auto_fulfil: true,
  max_quantity: 3,
  asks_needed_by: true,
  missing_translations: [],
  can_manage: false,
  version: 1,
  expected_delivery: {
    amount: 3,
    unit: 'business_days',
    around_the_clock: false,
    at: '2026-11-24T10:00:00Z',
  },
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function api(routes: Record<string, unknown> = {}, features?: Feature[]) {
  const fake = fakeApi({
    'GET /api/v1/auth/me': { body: session },
    'GET /api/v1/entitlements': {
      body: features === undefined ? fakeEntitlements() : fakeEntitlements({ features }),
    },
    'GET /api/v1/announcements/feed': { body: { items: [], next_change_in_seconds: null } },
    'GET /api/v1/catalog/categories': { body: [] },
    'GET /api/v1/catalog/items': { body: [item] },
    [`GET /api/v1/catalog/items/${ITEM}`]: { body: item },
    'GET /api/v1/portal/incidents/on-behalf-people': { body: [] },
    'POST /api/v1/service-requests': {
      status: 201,
      body: { id: SR, display_id: 'SR-71' },
    },
    ...routes,
  });
  restore = fake.restore;
  return fake;
}

describe('raising a request in the portal (WP-047a S1)', () => {
  it('asks a quantity up to the item maximum and shows the expected date', async () => {
    window.history.pushState({}, '', `/catalog/items/${ITEM}`);
    const fake = api();
    render(<App />);
    const quantity = await screen.findByTestId('portal-cat-quantity');
    expect(screen.getByTestId('portal-cat-expected').textContent).toContain('Expected delivery');
    expect(screen.getByTestId('portal-cat-needed-by')).toBeDefined();
    const input = quantity instanceof HTMLInputElement ? quantity : quantity.querySelector('input');
    if (input === null) throw new Error('no quantity input');
    fireEvent.change(input, { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('Size'), { target: { value: '27 inch' } });
    fireEvent.click(screen.getByTestId('portal-cat-send'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/service-requests')).toHaveLength(1);
    });
    const body = fake.find('POST', '/api/v1/service-requests')[0]?.body as Record<string, unknown>;
    expect(body.quantity).toBe(2);
    expect(body.subject).toBe('Monitor');
  });

  it('on Essentials (no catalogue feature) asks no quantity', async () => {
    window.history.pushState({}, '', `/catalog/items/${ITEM}`);
    api({}, ['incident', 'service_request', 'knowledge', 'sla']);
    render(<App />);
    await screen.findByTestId('portal-cat-form');
    expect(screen.queryByTestId('portal-cat-quantity')).toBeNull();
    expect(screen.getByTestId('portal-cat-needed-by')).toBeDefined(); // Essentials keeps it
  });

  it('request again fills the earlier answers and says what it left out', async () => {
    window.history.pushState({}, '', `/catalog/items/${ITEM}?again=${SR}`);
    api({
      [`GET /api/v1/portal/service-requests/${SR}/request-again`]: {
        body: {
          catalog_item_id: ITEM,
          available: true,
          reason: null,
          answers: { size: '24 inch' },
          dropped: ['colour'],
        },
      },
    });
    render(<App />);
    expect((await screen.findByTestId('portal-cat-again-dropped')).textContent).toContain(
      '1 earlier answer no longer applies',
    );
    await waitFor(() => {
      expect(screen.getByLabelText<HTMLInputElement>('Size').value).toBe('24 inch');
    });
  });

  it('a templated subject is left to the server when none is typed', async () => {
    window.history.pushState({}, '', `/catalog/items/${ITEM}`);
    const fake = api({
      [`GET /api/v1/catalog/items/${ITEM}`]: {
        body: { ...item, subject_template: 'Monitor {size}' },
      },
    });
    render(<App />);
    const subject = await screen.findByTestId('portal-cat-subject');
    expect((subject as HTMLInputElement).value).toBe('');
    fireEvent.change(screen.getByLabelText('Size'), { target: { value: '27 inch' } });
    fireEvent.click(screen.getByTestId('portal-cat-send'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/service-requests')).toHaveLength(1);
    });
    const body = fake.find('POST', '/api/v1/service-requests')[0]?.body as Record<string, unknown>;
    expect('subject' in body).toBe(false);
  });
});

describe('request again on a past request (REQ-SR-016)', () => {
  const record = {
    id: SR,
    display_id: 'SR-71',
    subject: 'Monitor',
    portal_status: 'closed',
    reach: 'own',
    requester_id: session.user.id,
    on_behalf_of_id: null,
    catalog_item_id: ITEM,
    answers: { size: '24 inch' },
    approval_status: 'not_needed',
    quantity: null,
    needed_by: null,
    expected_delivery_at: null,
    needed_earlier: false,
    created_at: '2026-11-03T09:00:00Z',
    updated_at: '2026-11-03T10:00:00Z',
    resolution: null,
    resolution_due_at: null,
    version: 2,
  };
  const routes = {
    [`GET /api/v1/portal/service-requests/${SR}`]: { body: record },
    [`GET /api/v1/portal/service-requests/${SR}/steps`]: {
      body: { items: [], done: 0, total: 0 },
    },
    [`GET /api/v1/service-requests/${SR}/approvals`]: { body: [] },
    [`GET /api/v1/portal/service-requests/${SR}/conversation`]: { body: { items: [] } },
  };

  it('offers it on your own request', async () => {
    window.history.pushState({}, '', `/service-requests/${SR}`);
    api({
      ...routes,
      [`GET /api/v1/portal/service-requests/${SR}/request-again`]: {
        body: { catalog_item_id: ITEM, available: true, reason: null, answers: {}, dropped: [] },
      },
    });
    render(<App />);
    expect((await screen.findByTestId('portal-request-again')).textContent).toBe('Request again');
  });

  it('disables it with the reason when the item is retired (AC3)', async () => {
    window.history.pushState({}, '', `/service-requests/${SR}`);
    api({
      ...routes,
      [`GET /api/v1/portal/service-requests/${SR}/request-again`]: {
        body: {
          catalog_item_id: ITEM,
          available: false,
          reason: 'catalog_item_retired',
          answers: {},
          dropped: [],
        },
      },
    });
    render(<App />);
    const disabled = await screen.findByTestId('portal-request-again-disabled');
    expect(disabled.querySelector('button')?.disabled).toBe(true);
  });
});

describe('the conversation on a request (WP-047a S3a; REQ-SR-037)', () => {
  const open = {
    id: SR,
    display_id: 'SR-72',
    subject: 'Monitor',
    portal_status: 'awaiting_approval',
    reach: 'own',
    requester_id: session.user.id,
    on_behalf_of_id: null,
    catalog_item_id: ITEM,
    answers: {},
    approval_status: 'pending',
    quantity: null,
    needed_by: null,
    expected_delivery_at: null,
    needed_earlier: false,
    created_at: '2026-11-03T09:00:00Z',
    updated_at: '2026-11-03T10:00:00Z',
    resolution: null,
    resolution_due_at: null,
    version: 2,
  };

  it("shows the approver's question and sends the requester's answer", async () => {
    window.history.pushState({}, '', `/service-requests/${SR}`);
    const fake = api({
      [`GET /api/v1/portal/service-requests/${SR}`]: { body: open },
      [`GET /api/v1/portal/service-requests/${SR}/steps`]: {
        body: { items: [], done: 0, total: 0 },
      },
      [`GET /api/v1/service-requests/${SR}/approvals`]: { body: [] },
      [`GET /api/v1/portal/service-requests/${SR}/request-again`]: {
        body: { catalog_item_id: ITEM, available: true, reason: null, answers: {}, dropped: [] },
      },
      [`GET /api/v1/portal/service-requests/${SR}/conversation`]: {
        body: {
          items: [
            {
              id: '01a1a2b3-0000-7000-8000-00000000e571',
              kind: 'reply',
              body: '<p>Which size do you need?</p>',
              created_at: '2026-11-24T09:00:00Z',
              author_name: 'Omar Manager',
              by_you: false,
            },
          ],
        },
      },
      [`POST /api/v1/portal/service-requests/${SR}/replies`]: { status: 201, body: open },
    });
    render(<App />);
    const talk = await screen.findByTestId('portal-request-conversation');
    expect(await screen.findByText('Which size do you need?')).toBeDefined();
    expect(talk.textContent).toContain('Omar Manager');
    expect(await screen.findByTestId('portal-request-reply-send')).toBeDefined();
    expect(fake.find('GET', `/api/v1/portal/service-requests/${SR}/conversation`)).toHaveLength(1);
  });
});

describe('a request made from mail asks only its missing answers (WP-047a S4)', () => {
  it('REQ-SR-017 AC2: the completion page asks what is missing, then submits', async () => {
    const [size] = item.questions;
    if (size === undefined) throw new Error('the item asks a size');
    const withTwo: CatalogItem = {
      ...item,
      questions: [
        ...item.questions,
        { ...size, key: 'colour', label: { en: 'Colour' }, required: false },
      ],
    };
    window.history.pushState({}, '', `/service-requests/${SR}/complete`);
    const fake = api({
      [`GET /api/v1/catalog/items/${ITEM}`]: { body: withTwo },
      [`GET /api/v1/portal/service-requests/${SR}/missing-answers`]: {
        body: { catalog_item_id: ITEM, missing: ['size'], version: 3 },
      },
      [`PUT /api/v1/portal/service-requests/${SR}/missing-answers`]: {
        body: { id: SR, display_id: 'SR-71' },
      },
    });
    render(<App />);
    await screen.findByTestId('portal-complete');
    expect(screen.queryByLabelText('Colour')).toBeNull(); // only the missing one
    const send = screen.getByTestId('portal-complete-send');
    expect(send).toHaveProperty('disabled', true);
    fireEvent.change(screen.getByLabelText('Size'), { target: { value: '27 inch' } });
    fireEvent.click(send);
    await waitFor(() => {
      expect(
        fake.find('PUT', `/api/v1/portal/service-requests/${SR}/missing-answers`),
      ).toHaveLength(1);
    });
    const sent = fake.find('PUT', `/api/v1/portal/service-requests/${SR}/missing-answers`)[0];
    expect(sent?.body).toEqual({ answers: { size: '27 inch' } });
    expect(sent?.headers.get('If-Match')).toBe('"3"');
  });

  it('a request not waiting for answers says so', async () => {
    window.history.pushState({}, '', `/service-requests/${SR}/complete`);
    api({
      [`GET /api/v1/portal/service-requests/${SR}/missing-answers`]: {
        status: 404,
        body: { code: 'work_item_not_found', message_key: 'errors.work_item_not_found' },
      },
    });
    render(<App />);
    expect(await screen.findByText('This request is not waiting for answers.')).toBeDefined();
  });
});
