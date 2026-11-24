import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { CatalogCategory, CatalogItem } from '@supportx/api-client';

import { App } from '../../../App';
import { consoleApi, fakeEntitlements, fakeSession, problem } from '../../../test/api';

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
  asks_needed_by: false,
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
    // QA10V-23: the description's language switch names the language, never "Name in …".
    const langs = await screen.findByTestId('cat-description-lang');
    expect(langs.textContent).toBe('EnglishArabicUrdu');
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

  it('WP-047a S1: an item may ask a quantity up to a maximum, and when it is needed', async () => {
    window.history.pushState({}, '', `/admin/catalog/items/${ITEM}`);
    const fake = api({
      [`PATCH /api/v1/catalog/items/${ITEM}`]: {
        body: { ...laptop, max_quantity: 10, asks_needed_by: true, version: 4 },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: /Fulfil/ }));
    fireEvent.click(await screen.findByTestId('catalog-asks-quantity'));
    expect(await screen.findByTestId('catalog-max-quantity')).toBeDefined();
    fireEvent.click(screen.getByTestId('catalog-asks-needed-by'));
    fireEvent.click(screen.getByTestId('cat-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/catalog/items/${ITEM}`)).toHaveLength(1);
    });
    expect(fake.find('PATCH', `/api/v1/catalog/items/${ITEM}`)[0]?.body).toEqual({
      max_quantity: 10,
      asks_needed_by: true,
    });
  });
});

// WP-047a S2a (REQ-SR-029..032): the stages editor.
describe('Admin › Service catalog › approval stages', () => {
  it('turns one stage into two, runs them in parallel and saves the list', async () => {
    window.history.pushState({}, '', `/admin/catalog/items/${ITEM}`);
    const fake = api({
      [`PATCH /api/v1/catalog/items/${ITEM}`]: { body: { ...laptop, version: 4 } },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Approval' }));
    fireEvent.click(await screen.findByTestId('cat-approval-on'));
    fireEvent.click(await screen.findByTestId('cat-stages-start'));
    expect(await screen.findByTestId('cat-stage-0')).toBeDefined();
    const second = await screen.findByTestId('cat-stage-1');
    expect(within(second).getByText('Stage 2')).toBeDefined();
    fireEvent.click(screen.getByTestId('cat-stage-1-parallel'));
    // The last stage can't move further down, and one stage left can't be removed.
    expect(
      within(second).getByRole('button', { name: 'Move stage 2 down' }).hasAttribute('disabled'),
    ).toBe(true);
    fireEvent.click(screen.getByTestId('cat-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/catalog/items/${ITEM}`)).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', `/api/v1/catalog/items/${ITEM}`);
    const approval = (sent?.body as { approval: { stages: Record<string, unknown>[] } }).approval;
    expect(approval.stages).toHaveLength(2);
    const [one, two] = approval.stages;
    expect(one?.parallel_group).toBeTruthy();
    expect(two?.parallel_group).toBe(one?.parallel_group);
    expect(two?.approvers).toEqual([{ kind: 'requested_for_manager' }]);
  });

  it('removing a stage dissolves a parallel group left with one stage', async () => {
    window.history.pushState({}, '', `/admin/catalog/items/${ITEM}`);
    const paired = {
      ...laptop,
      approval: {
        approvers: [{ kind: 'requested_for_manager' as const, person_id: null }],
        rule: 'any' as const,
        comments_required: false,
        self_approval: false,
        stages: [
          {
            approvers: [{ kind: 'requested_for_manager' as const }],
            rule: 'any' as const,
            comments_required: false,
            self_approval: false,
            parallel_group: 'p1',
          },
          {
            approvers: [{ kind: 'department_head' as const }],
            rule: 'all' as const,
            comments_required: false,
            self_approval: false,
            parallel_group: 'p1',
          },
        ],
      },
    };
    const fake = api({
      [`GET /api/v1/catalog/items/${ITEM}`]: { body: paired },
      [`PATCH /api/v1/catalog/items/${ITEM}`]: { body: { ...paired, version: 4 } },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Approval' }));
    fireEvent.click(await screen.findByTestId('cat-stage-remove-1'));
    fireEvent.click(screen.getByTestId('cat-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/catalog/items/${ITEM}`)).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', `/api/v1/catalog/items/${ITEM}`);
    const approval = (sent?.body as { approval: { stages: Record<string, unknown>[] } }).approval;
    expect(approval.stages).toHaveLength(1);
    expect(approval.stages[0]?.parallel_group ?? null).toBeNull();
  });
});

// Lane C's #582 notes: an Essentials tenant that still has a staged item (after a downgrade).
describe('Admin › Service catalog › escalation (WP-047a S3a; REQ-SR-034)', () => {
  it('a single stage chooses where it escalates, on every edition, and saves it', async () => {
    window.history.pushState({}, '', `/admin/catalog/items/${ITEM}`);
    const fake = api({
      'GET /api/v1/entitlements': {
        body: fakeEntitlements({
          edition: 'essentials',
          features: ['incident', 'service_request'],
        }),
      },
      [`PATCH /api/v1/catalog/items/${ITEM}`]: { body: { ...laptop, version: 4 } },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Approval' }));
    fireEvent.click(await screen.findByTestId('cat-approval-on'));
    const select = await screen.findByRole('combobox', { name: 'Escalate to' });
    fireEvent.mouseDown(select);
    fireEvent.click(await screen.findByTitle("The approver's manager"));
    fireEvent.click(screen.getByTestId('cat-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/catalog/items/${ITEM}`)).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', `/api/v1/catalog/items/${ITEM}`);
    const approval = (sent?.body as { approval: { escalate_to: string; stages?: unknown } })
      .approval;
    expect(approval.escalate_to).toBe('approver_manager');
    expect(approval.stages).toBeUndefined(); // still today's single stage: no Professional part
  });
});

describe('Admin › Service catalog › automatic approval rules (REQ-SR-033)', () => {
  it('a stage at its 5-rule cap cannot add another, and says why', async () => {
    window.history.pushState({}, '', `/admin/catalog/items/${ITEM}`);
    const rule = (n: number) => ({
      name: { en: `Rule ${String(n)}` },
      condition: { field: 'quantity', op: 'eq' as const, value: n },
    });
    const stage = {
      approvers: [{ kind: 'requested_for_manager' as const }],
      rule: 'any' as const,
      comments_required: false,
      self_approval: false,
      auto_rules: [1, 2, 3, 4, 5].map(rule),
    };
    api({
      [`GET /api/v1/catalog/items/${ITEM}`]: {
        body: {
          ...laptop,
          approval: {
            approvers: [{ kind: 'requested_for_manager' as const, person_id: null }],
            rule: 'any' as const,
            comments_required: false,
            self_approval: false,
            stages: [stage],
          },
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Approval' }));
    const auto = await screen.findByTestId('cat-stage-0-auto');
    expect(within(auto).getByTestId('cat-stage-0-auto-rule-4')).toBeDefined();
    expect(within(auto).getByTestId<HTMLButtonElement>('cat-stage-0-auto-rule-add').disabled).toBe(
      true,
    );
    fireEvent.mouseOver(within(auto).getByTestId('disabled-why'));
    expect(await screen.findByText('A stage can have at most 5 rules.')).toBeDefined();
    // Removing one frees the button again.
    fireEvent.click(within(auto).getByTestId('cat-stage-0-auto-rule-4-remove'));
    await waitFor(() => {
      expect(
        within(auto).getByTestId<HTMLButtonElement>('cat-stage-0-auto-rule-add').disabled,
      ).toBe(false);
    });
  });
});

describe('Admin › Service catalog › stages without the Professional edition', () => {
  it('explains how to save, disables what is Professional and saves a rename alone', async () => {
    window.history.pushState({}, '', `/admin/catalog/items/${ITEM}`);
    const staged = {
      ...laptop,
      approval: {
        approvers: [{ kind: 'requested_for_manager' as const, person_id: null }],
        rule: 'any' as const,
        comments_required: false,
        self_approval: false,
        stages: [
          {
            approvers: [{ kind: 'requested_for_manager' as const }],
            rule: 'any' as const,
            comments_required: false,
            self_approval: false,
          },
          {
            approvers: [{ kind: 'department_head' as const }],
            rule: 'all' as const,
            comments_required: false,
            self_approval: false,
          },
        ],
      },
    };
    const fake = api({
      'GET /api/v1/entitlements': {
        body: fakeEntitlements({
          edition: 'essentials',
          features: ['incident', 'service_request'],
        }),
      },
      [`GET /api/v1/catalog/items/${ITEM}`]: { body: staged },
      [`PATCH /api/v1/catalog/items/${ITEM}`]: { body: { ...staged, version: 4 } },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Approval' }));
    const alert = await screen.findByTestId('cat-stages-unlicensed');
    expect(alert.textContent).toContain('reduce it to one stage');
    expect(screen.getByTestId('cat-stage-add').hasAttribute('disabled')).toBe(true);
    // Removing a stage stays allowed: that is how the item is reduced.
    expect(screen.getByTestId('cat-stage-remove-1').hasAttribute('disabled')).toBe(false);
    // A rename sends only the name, never the stages it cannot save.
    fireEvent.click(screen.getByRole('tab', { name: 'Details' }));
    fireEvent.change(await screen.findByTestId('cat-name-en'), {
      target: { value: 'New laptop (renamed)' },
    });
    fireEvent.click(screen.getByTestId('cat-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/catalog/items/${ITEM}`)).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', `/api/v1/catalog/items/${ITEM}`);
    expect(Object.keys(sent?.body as object)).toEqual(['names']);
  });
});
