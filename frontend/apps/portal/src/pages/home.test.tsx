import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { CatalogItem } from '@supportx/api-client';
import { fakeApi, fakeEntitlements, fakeSession } from '@supportx/api-client/testing';

import { App } from '../App';

// WP-032 S1: the portal home (starting points, live summary, featured and most requested),
// one search box for everything, and "what happens next" after submitting.

const REQUESTER = fakeSession({
  display_name: 'Yusra Requester',
  user_type: 'requester',
  roles: ['requester'],
});

function item(id: string, name: string, extra: Partial<CatalogItem> = {}): CatalogItem {
  return {
    id,
    names: { en: name },
    summaries: { en: `${name} summary` },
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
    auto_fulfil: false,
    can_manage: false,
    version: 1,
    ...extra,
  };
}

const LAPTOP = item('01a1a2b3-0000-7000-8000-00000000d001', 'New laptop', {
  featured: true,
  approval: {
    approvers: [{ kind: 'requested_for_manager', person_id: null }],
    comments_required: false,
    self_approval: false,
  },
});
const VPN = item('01a1a2b3-0000-7000-8000-00000000d002', 'VPN access');

let restore: () => void = () => undefined;
function api(routes: Record<string, unknown> = {}) {
  const fake = fakeApi({
    'GET /api/v1/auth/me': { body: REQUESTER },
    'GET /api/v1/entitlements': { body: fakeEntitlements() },
    'GET /api/v1/announcements/feed': { body: { items: [], next_change_in_seconds: null } },
    'GET /api/v1/portal/summary': {
      body: {
        open_by_status: [
          { status: 'in_progress', count: 2 },
          { status: 'awaiting_approval', count: 1 },
        ],
        approvals: 1,
        tasks: 0,
      },
    },
    'GET /api/v1/catalog/items': { body: [LAPTOP] },
    'GET /api/v1/catalog/items/popular': { body: [LAPTOP, VPN] },
    ...routes,
  });
  restore = fake.restore;
  return fake;
}

describe('portal home and search (WP-032)', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/');
  });
  afterEach(() => {
    restore();
  });

  it('offers three starting points, my summary, and featured then most requested items', async () => {
    api();
    render(<App />);
    expect(await screen.findByTestId('portal-start-report')).toBeDefined();
    expect(screen.getByTestId('portal-start-request')).toBeDefined();
    expect(screen.getByTestId('portal-start-answer')).toBeDefined();
    const summary = await screen.findByTestId('portal-summary');
    expect(within(summary).getByText('3')).toBeDefined(); // open requests
    expect(within(screen.getByTestId('portal-summary-approvals')).getByText('1')).toBeDefined();
    const featured = await screen.findByTestId('portal-featured');
    expect(within(featured).getByText('New laptop')).toBeDefined();
    expect(within(featured).getByText('Needs approval')).toBeDefined();
    // Most requested leaves out what is already featured.
    const popular = await screen.findByTestId('portal-popular');
    expect(within(popular).queryByText('New laptop')).toBeNull();
    expect(within(popular).getByText('VPN access')).toBeDefined();
  });

  it('searches everything in groups, and offers to report when nothing is found', async () => {
    window.history.pushState({}, '', '/search?q=vpn');
    api({
      'GET /api/v1/catalog/items/search': { body: [VPN] },
      'GET /api/v1/knowledge/articles': { body: [] },
      'GET /api/v1/portal/incidents': { body: { items: [], next_cursor: null, has_more: false } },
      'GET /api/v1/portal/service-requests': {
        body: { items: [], next_cursor: null, has_more: false },
      },
    });
    render(<App />);
    const items = await screen.findByTestId('portal-search-items');
    expect(await within(items).findByText('VPN access')).toBeDefined();
    expect(screen.queryByTestId('portal-search-nothing')).toBeNull();
  });

  it('when nothing matches, the report form opens with the words as its subject', async () => {
    window.history.pushState({}, '', '/search?q=printer%20jam');
    api({
      'GET /api/v1/catalog/items/search': { body: [] },
      'GET /api/v1/knowledge/articles': { body: [] },
      'GET /api/v1/portal/incidents': { body: { items: [], next_cursor: null, has_more: false } },
      'GET /api/v1/portal/service-requests': {
        body: { items: [], next_cursor: null, has_more: false },
      },
      'GET /api/v1/portal/incidents/templates': { body: [] },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('portal-search-report'));
    await waitFor(() => {
      expect(window.location.pathname).toBe('/requests/new');
    });
    expect(new URLSearchParams(window.location.search).get('subject')).toBe('printer jam');
  });
});
