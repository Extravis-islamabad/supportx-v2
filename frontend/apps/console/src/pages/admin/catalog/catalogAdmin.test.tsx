import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { CatalogCategory, CatalogItem } from '@supportx/api-client';

import { App } from '../../../App';
import { consoleApi, fakeSession, problem } from '../../../test/api';

const ADMIN = fakeSession({ roles: ['tenant_admin', 'technician'] });

// WP-031 s2: Admin › Service catalog: the tree and items, the starter banner, one item's tabs,
// saving with If-Match, the preview as a requester sees it.

const CAT = '01a1a2b3-0000-7000-8000-00000000ca01';
const ITEM = '01a1a2b3-0000-7000-8000-00000000c101';
const GROUP = '01a1a2b3-0000-7000-8000-00000000g001';

const hardware: CatalogCategory = {
  id: CAT,
  names: { en: 'Hardware', ar: 'الأجهزة' },
  descriptions: {},
  sort_order: 0,
  parent_id: null,
  icon: 'laptop',
  enabled: true,
  version: 1,
};

const laptop: CatalogItem = {
  id: ITEM,
  names: { en: 'New laptop' },
  summaries: { en: 'A laptop for a new starter.' },
  descriptions: { en: '<p>Ask your manager first.</p>' },
  keywords: {},
  icon: 'laptop',
  category_id: CAT,
  extra_category_ids: [],
  kind: 'service',
  template_id: null,
  audience: 'everyone',
  status: 'draft',
  enabled: false,
  publish_at: null,
  retire_at: null,
  published_at: null,
  owner_id: null,
  featured: false,
  sort_order: 0,
  subject_template: null,
  requesters_see_approval: true,
  starter: true,
  questions: [
    {
      key: 'model',
      label: { en: 'Model' },
      kind: 'choice',
      required: true,
      options: ['standard', 'performance'],
      option_labels: { standard: { en: 'Standard' }, performance: { en: 'Performance' } },
      help: {},
      default: null,
      shown_to: ['requester', 'technician', 'approver'],
    },
    {
      key: 'asset_tag',
      label: { en: 'Asset tag' },
      kind: 'text',
      required: false,
      options: [],
      option_labels: {},
      help: {},
      default: null,
      shown_to: ['technician'],
    },
  ],
  approval: null,
  plan: [],
  default_priority: 'p3',
  requester_sets_priority: false,
  sla_policy_id: null,
  group_id: GROUP,
  technician_id: null,
  technician_after_approval: false,
  count_approval_time: false,
  auto_fulfil: true,
  missing_translations: [
    { field: 'names', language: 'ar' },
    { field: 'questions.0.label', language: 'ur' },
  ],
  can_manage: true,
  version: 3,
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function api(routes: Record<string, unknown> = {}) {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/catalog/categories': { body: [hardware] },
      'GET /api/v1/catalog/items': { body: [laptop] },
      [`GET /api/v1/catalog/items/${ITEM}`]: { body: laptop },
      'GET /api/v1/catalog/starter': { body: { drafts: 14 } },
      'GET /api/v1/catalog/settings': {
        body: { hide_default_incident_template: false, version: 1 },
      },
      'GET /api/v1/organization/groups': {
        body: [{ id: GROUP, name: 'Service desk', member_ids: [], disabled: false, version: 1 }],
      },
      ...routes,
    },
  });
  restore = fake.restore;
  return fake;
}

describe('Admin › Service catalog', () => {
  it('lists the tree and the items, and offers to publish the starter drafts', async () => {
    window.history.pushState({}, '', '/admin/catalog');
    api();
    render(<App />);
    expect(await screen.findByTestId(`cat-node-${CAT}`)).toBeDefined();
    expect((await screen.findByTestId(`cat-item-${ITEM}`)).textContent).toBe('New laptop');
    expect(screen.getByTestId(`cat-status-${ITEM}`).textContent).toBe('Draft');
    const banner = await screen.findByTestId('cat-starter');
    expect(banner.textContent).toContain('14 starter items are waiting as drafts');
  });

  it('a new item is a draft created once with an Idempotency-Key', async () => {
    window.history.pushState({}, '', '/admin/catalog/items/new');
    const fake = api({
      'POST /api/v1/catalog/items': { status: 201, body: { ...laptop, id: ITEM, version: 1 } },
    });
    render(<App />);
    fireEvent.change(await screen.findByTestId('cat-name-en'), {
      target: { value: 'New laptop' },
    });
    fireEvent.click(screen.getByTestId('cat-save'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/catalog/items')).toHaveLength(1);
    });
    const [sent] = fake.find('POST', '/api/v1/catalog/items');
    expect(sent?.body).toMatchObject({ names: { en: 'New laptop' }, kind: 'service' });
    expect(sent?.headers.get('Idempotency-Key')).toBeTruthy();
  });

  it('publishing sends only the status, with If-Match on the version opened', async () => {
    window.history.pushState({}, '', `/admin/catalog/items/${ITEM}`);
    const fake = api({
      [`PATCH /api/v1/catalog/items/${ITEM}`]: {
        body: { ...laptop, status: 'published', enabled: true, version: 4 },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Publishing' }));
    fireEvent.click(await screen.findByTestId('cat-publish'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/catalog/items/${ITEM}`)).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', `/api/v1/catalog/items/${ITEM}`);
    expect(sent?.body).toEqual({ status: 'published' });
    expect(sent?.headers.get('If-Match')).toBe('"3"');
  });

  it('QA10-P3-08: a refused publish names the missing field and opens its tab', async () => {
    window.history.pushState({}, '', `/admin/catalog/items/${ITEM}`);
    api({
      [`PATCH /api/v1/catalog/items/${ITEM}`]: {
        status: 422,
        body: problem(422, 'validation_failed', {
          errors: [
            {
              field: 'body.group_id',
              code: 'required',
              message_key: 'errors.field.required',
              params: {},
            },
          ],
        }),
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Publishing' }));
    fireEvent.click(await screen.findByTestId('cat-publish'));
    const problems = await screen.findByTestId('cat-item-problems');
    expect(problems.textContent).toContain('Fulfilment group: This field is required.');
    expect(
      screen.getByRole('tab', { name: 'SLA and assignment' }).getAttribute('aria-selected'),
    ).toBe('true');
  });

  it('the preview shows the description first and only the requester’s questions', async () => {
    window.history.pushState({}, '', `/admin/catalog/items/${ITEM}`);
    api();
    render(<App />);
    fireEvent.click(await screen.findByTestId('cat-preview'));
    const drawer = await screen.findByTestId('cat-preview-drawer');
    expect(within(drawer).getByTestId('cat-preview-description').textContent).toContain(
      'Ask your manager first.',
    );
    expect(within(drawer).getByText('Model')).toBeDefined();
    expect(within(drawer).queryByText('Asset tag')).toBeNull(); // technicians only
    expect(within(drawer).getByRole('radio', { name: 'Standard' })).toHaveProperty(
      'disabled',
      true,
    );
  });

  it('names missing translations in words, never by their path', async () => {
    window.history.pushState({}, '', `/admin/catalog/items/${ITEM}`);
    api();
    render(<App />);
    fireEvent.mouseOver(await screen.findByTestId('cat-missing'));
    const listed = await screen.findByTestId('cat-missing-list');
    expect(listed.textContent).toContain('Name: no Arabic text yet');
    expect(listed.textContent).toContain('Question 1: no Urdu text yet');
    expect(listed.textContent).not.toContain('questions.0');
  });
});
