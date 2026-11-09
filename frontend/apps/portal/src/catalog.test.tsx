import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { CatalogItem } from '@supportx/api-client';
import { fakeApi, fakeEntitlements, fakeSession } from '@supportx/api-client/testing';

import { App } from './App';

// WP-031 s2: the catalog for requesters: browse, search, an item's form (description first,
// the requester's questions only), sent once; a "report a problem" entry opens the incident form.

const CAT = '01a1a2b3-0000-7000-8000-00000000ca01';
const ITEM = '01a1a2b3-0000-7000-8000-00000000c101';
const ENTRY = '01a1a2b3-0000-7000-8000-00000000c102';
const TEMPLATE = '01a1a2b3-0000-7000-8000-00000000t001';
const SR = '01a1a2b3-0000-7000-8000-00000000c501';
const session = fakeSession({ user_type: 'requester', roles: ['requester'] });

const base: Omit<CatalogItem, 'id' | 'names' | 'kind'> = {
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
  starter: false,
  questions: [],
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
  missing_translations: [],
  can_manage: false,
  version: 1,
};

const reset: CatalogItem = {
  ...base,
  id: ITEM,
  kind: 'service',
  names: { en: 'Password or MFA reset help', ar: 'المساعدة في إعادة تعيين كلمة المرور' },
  summaries: { en: 'Locked out? Try Forgot password? first.' },
  descriptions: { en: '<p>Before you ask: choose Forgot password? on the sign-in page.</p>' },
  questions: [
    {
      key: 'account',
      label: { en: 'Which account' },
      kind: 'text',
      required: true,
      options: [],
      option_labels: {},
      help: {},
      default: null,
      shown_to: ['requester', 'technician', 'approver'],
    },
    {
      key: 'checked_identity',
      label: { en: 'Identity checked' },
      kind: 'yes_no',
      required: false,
      options: [],
      option_labels: {},
      help: {},
      default: null,
      shown_to: ['technician'],
    },
  ],
};
const printer: CatalogItem = {
  ...base,
  id: ENTRY,
  kind: 'incident_template',
  template_id: TEMPLATE,
  featured: false,
  names: { en: 'The printer does not print' },
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function api(routes: Record<string, unknown> = {}) {
  const fake = fakeApi({
    'GET /api/v1/auth/me': { body: session },
    'GET /api/v1/entitlements': { body: fakeEntitlements() },
    'GET /api/v1/announcements/feed': { body: { items: [], next_change_in_seconds: null } },
    'GET /api/v1/catalog/categories': {
      body: [
        {
          id: CAT,
          names: { en: 'Accounts and access' },
          descriptions: {},
          sort_order: 0,
          parent_id: null,
          icon: 'account',
          enabled: true,
          version: 1,
        },
      ],
    },
    'GET /api/v1/catalog/items': { body: [reset, printer] },
    [`GET /api/v1/catalog/items/${ITEM}`]: { body: reset },
    'GET /api/v1/catalog/items/search': { body: [reset] },
    'GET /api/v1/portal/incidents/on-behalf-people': { body: [] },
    ...routes,
  });
  restore = fake.restore;
  return fake;
}

describe('portal catalog', () => {
  it('shows the featured items and the categories, and a problem entry opens the incident form', async () => {
    window.history.pushState({}, '', '/catalog');
    api();
    render(<App />);
    expect((await screen.findByTestId(`portal-cat-item-${ITEM}`)).textContent).toContain(
      'Password or MFA reset help',
    );
    expect(await screen.findByTestId(`portal-cat-category-${CAT}`)).toBeDefined();
    fireEvent.click(await screen.findByTestId(`portal-cat-category-${CAT}`));
    const entry = await screen.findByTestId(`portal-cat-item-${ENTRY}`);
    expect(entry.getAttribute('href')).toBe(`/requests/new?template=${TEMPLATE}`);
  });

  it('searches across the catalog', async () => {
    window.history.pushState({}, '', '/catalog');
    const fake = api();
    render(<App />);
    fireEvent.change(await screen.findByTestId('portal-cat-search'), {
      target: { value: 'parol' },
    });
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/catalog/items/search').length).toBeGreaterThan(0);
    });
    expect(await screen.findByTestId(`portal-cat-item-${ITEM}`)).toBeDefined();
  });

  it('an item shows its description before the form and sends only the requester’s answers', async () => {
    window.history.pushState({}, '', `/catalog/items/${ITEM}`);
    const fake = api({
      'POST /api/v1/service-requests': {
        status: 201,
        body: { id: SR, display_id: 'SR-9', version: 1 },
      },
    });
    render(<App />);
    const about = await screen.findByTestId('portal-cat-description');
    expect(about.textContent).toContain('Forgot password?');
    expect(screen.queryByText('Identity checked')).toBeNull(); // technicians only
    const send = screen.getByTestId('portal-cat-send');
    expect(send).toHaveProperty('disabled', true); // a required answer is missing
    fireEvent.change(screen.getByTestId('sr-q-account'), { target: { value: 'sara@demo.test' } });
    fireEvent.click(screen.getByTestId('portal-cat-send'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/service-requests')).toHaveLength(1);
    });
    const [sent] = fake.find('POST', '/api/v1/service-requests');
    expect(sent?.body).toMatchObject({
      subject: 'Password or MFA reset help',
      catalog_item_id: ITEM,
      answers: { account: 'sara@demo.test' },
    });
    expect(sent?.headers.get('Idempotency-Key')).toBeTruthy();
  });

  it('QA6-PRT-01: category tiles show their icon and item count; items show their icon', async () => {
    window.history.pushState({}, '', '/catalog');
    api();
    render(<App />);
    const tile = await screen.findByTestId(`portal-cat-category-${CAT}`);
    expect(tile.querySelector('[data-icon="account"]')).not.toBeNull();
    await waitFor(() => {
      expect(screen.getByTestId(`portal-cat-count-${CAT}`).textContent).toBe('2 items');
    });
    const item = await screen.findByTestId(`portal-cat-item-${ITEM}`);
    expect(item.querySelector('[data-testid="catalog-icon"]')).not.toBeNull();
  });

  it('QA6-PRT-01: with nothing featured, the most requested items are shown instead', async () => {
    window.history.pushState({}, '', '/catalog');
    const unfeatured = { ...reset, featured: false };
    const fake = api({
      'GET /api/v1/catalog/items': ({ url }: { url: URL }) => ({
        body: url.searchParams.get('featured') === 'true' ? [] : [unfeatured, printer],
      }),
      'GET /api/v1/catalog/items/popular': { body: [unfeatured] },
    });
    render(<App />);
    const section = await screen.findByRole('region', { name: 'Popular' });
    await waitFor(() => {
      expect(section.querySelector(`[data-testid="portal-cat-item-${ITEM}"]`)).not.toBeNull();
    });
    expect(fake.find('GET', '/api/v1/catalog/items/popular').length).toBeGreaterThan(0);
  });

  it('QA6-PRT-01: a request asks "What do you need?", not what is wrong', async () => {
    window.history.pushState({}, '', `/catalog/items/${ITEM}`);
    api();
    render(<App />);
    await screen.findByTestId('portal-cat-subject');
    expect(screen.getByText('What do you need?')).toBeDefined();
    expect(screen.queryByText('In a few words, what is wrong')).toBeNull();
  });

  it('QA6-PRT-02: the request form sits on a card', async () => {
    window.history.pushState({}, '', `/catalog/items/${ITEM}`);
    api();
    render(<App />);
    const card = await screen.findByTestId('portal-cat-form');
    expect(card.className).toContain('ant-card');
    expect(card.querySelector('[data-testid="portal-cat-subject"]')).not.toBeNull();
  });
});
