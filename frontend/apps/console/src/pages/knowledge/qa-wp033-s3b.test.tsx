import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { KbVersion } from '@supportx/api-client';
import { fakeKbArticle } from '@supportx/api-client/testing';
import { setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../App';
import { consoleApi, fakeSession, problem } from '../../test/api';

// WP-033 session 3b (D-120): the approval inbox and Admin › Knowledge.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const PUBLISHED = fakeKbArticle();
const LIVE = (PUBLISHED.published.en ?? {}) as KbVersion;
const REVIEW: KbVersion = {
  ...LIVE,
  id: '01900000-0000-7000-8000-00000000b102',
  number: 2,
  status: 'in_review',
  title: 'Reset your VPN token safely',
  body_html: '<p>Use the new portal.</p>',
  change_note: 'Portal moved',
  version: 4,
};
const IN_REVIEW = fakeKbArticle({ drafts: { en: REVIEW }, can_approve: true });
const FIRST = fakeKbArticle({
  id: '01900000-0000-7000-8000-00000000b002',
  display_id: 'KB-2',
  published: {},
  drafts: { en: { ...REVIEW, title: 'Printer jams', change_note: null } },
  can_approve: true,
});
const row = (article: typeof IN_REVIEW, title: string) => ({
  id: article.id,
  display_id: article.display_id,
  topic_id: article.topic_id,
  type_code: 'how_to',
  language: 'en',
  title,
  status: 'in_review',
  review_on: null,
  updated_at: '2026-11-02T08:00:00Z',
  owner_id: article.owner_id,
  author_id: article.owner_id,
  author_name: 'Tariq Technician',
  expired: false,
  withdrawn: false,
  review_due: false,
});
const TOPIC = {
  id: IN_REVIEW.topic_id,
  parent_id: null,
  depth: 1,
  sort_order: 0,
  names: { en: 'Network', ar: 'الشبكة' },
  description: null,
  icon: null,
  owner_id: null,
  tech_all: true,
  tech_groups: [],
  requesters: 'none',
  req_groups: [],
  req_sites: [],
  req_departments: [],
  version: 1,
};
const TYPES = [
  { code: 'how_to', names: {}, builtin: true, retired: false, review_months: 12, version: 1 },
  {
    code: 'custom_ab12',
    names: { en: 'Runbook', ar: 'دليل التشغيل' },
    builtin: false,
    retired: false,
    review_months: 6,
    version: 3,
  },
];
const SETTINGS = {
  prefix: 'KB',
  next_number: 43,
  self_approval: false,
  requesters_enabled: true,
  version: 5,
  defaults: { prefix: 'KB', self_approval: false, requesters_enabled: true },
};
const COMMON = {
  'GET /api/v1/knowledge/topics': { body: [TOPIC] },
  'GET /api/v1/knowledge/types': { body: TYPES },
  'GET /api/v1/knowledge/approvals/count': { body: { count: 2 } },
  'GET /api/v1/knowledge/settings': { body: SETTINGS },
};

function api(routes: Record<string, unknown>, me = ADMIN) {
  const fake = consoleApi({ me, routes: { ...COMMON, ...routes } });
  restore = fake.restore;
  return fake;
}

const inbox = (rows: unknown[] | (() => { body: unknown[] })) => ({
  'GET /api/v1/knowledge/articles': typeof rows === 'function' ? rows : { body: rows },
  [`GET /api/v1/knowledge/articles/${IN_REVIEW.id}`]: { body: IN_REVIEW },
  [`GET /api/v1/knowledge/articles/${FIRST.id}`]: { body: FIRST },
});

async function openItem(displayId: string) {
  fireEvent.click(await screen.findByTestId(`kb-inbox-item-${displayId}`));
  return screen.findByTestId('kb-inbox-preview');
}

describe('Approval inbox (D-120)', () => {
  it('previews the version under review beside what readers see now, with the note and the title change', async () => {
    window.history.pushState({}, '', '/knowledge/approvals');
    api(inbox([row(IN_REVIEW, REVIEW.title), row(FIRST, 'Printer jams')]));
    render(<App />);
    const queue = await screen.findByTestId('kb-inbox-queue');
    expect(await within(queue).findByText('Waiting for you (2)')).toBeDefined();
    expect(within(queue).getByText(/KB-1 · Network/)).toBeDefined();
    // Who wrote it (D-120): the author, in the queue itself.
    expect(within(queue).getAllByTestId('kb-inbox-author')[0]?.textContent).toBe(
      'By Tariq Technician',
    );
    expect(queue.textContent).not.toMatch(/in_review|how_to/);

    const preview = await openItem('KB-1');
    expect(within(preview).getByTestId('kb-inbox-review-body').textContent).toBe(
      'Use the new portal.',
    );
    expect(within(preview).getByTestId('kb-inbox-published-body').textContent).toContain(
      'Open the portal.',
    );
    expect(within(preview).getByTestId('kb-inbox-note').textContent).toContain('Portal moved');
    expect(within(preview).getByTestId('kb-inbox-title-changed').textContent).toContain(
      '“Reset your VPN token”',
    );
    // Only the two decisions: never edit, withdraw or delete here.
    expect(within(preview).getByTestId('kb-action-approve')).toBeDefined();
    expect(within(preview).getByTestId('kb-action-reject')).toBeDefined();
    expect(within(preview).queryByTestId('kb-action-withdraw')).toBeNull();
    expect(within(preview).queryByTestId('kb-action-delete')).toBeNull();
  });

  it('a first version says nothing is published yet; approve sends the draft version (If-Match)', async () => {
    window.history.pushState({}, '', '/knowledge/approvals');
    const fake = api({
      ...inbox([row(FIRST, 'Printer jams')]),
      [`POST /api/v1/knowledge/articles/${FIRST.id}/drafts/en/approve`]: { body: FIRST },
    });
    render(<App />);
    const preview = await openItem('KB-2');
    expect(within(preview).getByTestId('kb-inbox-first')).toBeDefined();
    fireEvent.click(within(preview).getByTestId('kb-action-approve'));
    await waitFor(() => {
      expect(
        fake.find('POST', `/api/v1/knowledge/articles/${FIRST.id}/drafts/en/approve`),
      ).toHaveLength(1);
    });
    const [call] = fake.find('POST', `/api/v1/knowledge/articles/${FIRST.id}/drafts/en/approve`);
    expect(call?.headers.get('If-Match')).toBe('"4"');
  });

  it('sending back needs a reason', async () => {
    window.history.pushState({}, '', '/knowledge/approvals');
    const fake = api({
      ...inbox([row(IN_REVIEW, REVIEW.title)]),
      [`POST /api/v1/knowledge/articles/${IN_REVIEW.id}/drafts/en/reject`]: { status: 204 },
    });
    render(<App />);
    const preview = await openItem('KB-1');
    fireEvent.click(within(preview).getByTestId('kb-action-reject'));
    const text = await screen.findByTestId('kb-step-text');
    const dialog = text.closest<HTMLElement>('.ant-modal');
    if (dialog === null) throw new Error('the reason dialog is not open');
    const ok = within(dialog).getAllByRole('button').at(-1) as HTMLButtonElement;
    expect(ok.disabled).toBe(true);
    fireEvent.change(text, { target: { value: 'Add the screenshots' } });
    expect(ok.disabled).toBe(false);
    fireEvent.click(ok);
    await waitFor(() => {
      const [call] = fake.find(
        'POST',
        `/api/v1/knowledge/articles/${IN_REVIEW.id}/drafts/en/reject`,
      );
      expect(call?.body).toEqual({ reason: 'Add the screenshots' });
    });
  });

  it('an article someone else decided leaves the queue live and says so', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', '/knowledge/approvals');
    let rows: unknown[] = [row(IN_REVIEW, REVIEW.title)];
    const fake = api(inbox(() => ({ body: rows })));
    render(<App />);
    await openItem('KB-1');
    const before = fake.find('GET', '/api/v1/knowledge/articles').length;
    rows = [];
    act(() => {
      realtime.publish(':broadcast', { type: 'knowledge.changed', ids: [] });
    });
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/knowledge/articles').length).toBeGreaterThan(before);
    });
    expect((await screen.findByTestId('kb-inbox-gone')).textContent).toContain(
      'Someone else has already decided this article.',
    );
  });

  it('an Arabic article under review reads right to left', async () => {
    const arabic = fakeKbArticle({
      default_language: 'ar',
      published: {},
      drafts: {
        ar: {
          ...REVIEW,
          language: 'ar',
          title: 'إعادة تعيين الرمز',
          body_html: '<p>افتح البوابة.</p>',
        },
      },
      can_approve: true,
    });
    window.history.pushState({}, '', '/knowledge/approvals');
    api({
      'GET /api/v1/knowledge/articles': {
        body: [{ ...row(arabic, 'إعادة تعيين الرمز'), language: 'ar' }],
      },
      [`GET /api/v1/knowledge/articles/${arabic.id}`]: { body: arabic },
    });
    render(<App />);
    const preview = await openItem('KB-1');
    expect(
      within(preview).getByTestId('kb-inbox-review-body').closest('[dir="rtl"]'),
    ).not.toBeNull();
  });

  it('a technician who may not approve gets "no access", not an empty inbox', async () => {
    window.history.pushState({}, '', '/knowledge/approvals');
    api(inbox([]), fakeSession());
    render(<App />);
    expect(await screen.findByText('Approval inbox')).toBeDefined();
    expect(screen.queryByTestId('kb-inbox-queue')).toBeNull();
  });
});

describe('Admin › Knowledge (D-120)', () => {
  it('shows each default, the next ID, and saves only what changed with If-Match', async () => {
    window.history.pushState({}, '', '/admin/knowledge');
    const fake = api({
      'PATCH /api/v1/knowledge/settings': { body: { ...SETTINGS, prefix: 'ART', version: 6 } },
    });
    render(<App />);
    expect(await screen.findByRole('tab', { name: 'Knowledge' })).toBeDefined();
    const card = await screen.findByTestId('kb-admin-general');
    expect(within(card).getAllByText('Default: No').length).toBeGreaterThan(0);
    expect(within(card).getByText('Default: KB')).toBeDefined();
    expect(within(card).getByTestId('kb-admin-next-id').textContent).toBe(
      'The next article will be KB-43.',
    );
    fireEvent.change(within(card).getByTestId('kb-admin-prefix'), { target: { value: 'art' } });
    await waitFor(() => {
      expect(within(card).getByTestId('kb-admin-next-id').textContent).toBe(
        'The next article will be ART-43.',
      );
    });
    fireEvent.click(within(card).getByTestId('kb-admin-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/knowledge/settings')).toHaveLength(1);
    });
    const [call] = fake.find('PATCH', '/api/v1/knowledge/settings');
    expect(call?.headers.get('If-Match')).toBe('"5"');
    expect(call?.body).toEqual({ prefix: 'ART' });
  });

  it("the server's field problems show at their field", async () => {
    window.history.pushState({}, '', '/admin/knowledge');
    api({
      'PATCH /api/v1/knowledge/settings': {
        status: 422,
        body: problem(422, 'validation_failed', {
          errors: [
            {
              field: 'body.next_number',
              code: 'number_already_used',
              message_key: 'errors.field.number_already_used',
              params: { minimum: 43 },
            },
          ],
        }),
      },
    });
    render(<App />);
    const card = await screen.findByTestId('kb-admin-general');
    fireEvent.change(within(card).getByTestId('kb-admin-next'), { target: { value: '7' } });
    fireEvent.click(within(card).getByTestId('kb-admin-save'));
    expect(
      await within(card).findByText('That number is already used. Choose 43 or higher.'),
    ).toBeDefined();
  });

  it('types: names by label, Arabic name required for a new one, built-in keeps its names', async () => {
    window.history.pushState({}, '', '/admin/knowledge');
    const fake = api({
      'POST /api/v1/knowledge/types': { status: 201, body: TYPES[1] },
      'PATCH /api/v1/knowledge/types/how_to': { body: { ...TYPES[0], review_months: 24 } },
      'PATCH /api/v1/knowledge/types/custom_ab12': { body: { ...TYPES[1], retired: true } },
    });
    render(<App />);
    const card = await screen.findByTestId('kb-admin-types');
    expect(await within(card).findByText('How-to')).toBeDefined();
    expect(within(card).getByText('Runbook')).toBeDefined();
    expect(within(card).getByText('12 months')).toBeDefined();
    expect(card.textContent).not.toMatch(/how_to|custom_ab12/);

    // A new type needs its Arabic name before anything is sent.
    fireEvent.click(within(card).getByTestId('kb-admin-type-add'));
    let dialog = await screen.findByTestId('kb-admin-type-dialog');
    fireEvent.change(within(document.body).getByTestId('kb-admin-type-en'), {
      target: { value: 'Checklist' },
    });
    fireEvent.click(within(dialog.closest('.ant-modal') ?? dialog).getByText('Save'));
    expect(await screen.findByText('This field is required.')).toBeDefined();
    expect(fake.find('POST', '/api/v1/knowledge/types')).toHaveLength(0);
    fireEvent.change(within(document.body).getByTestId('kb-admin-type-ar'), {
      target: { value: 'قائمة تحقق' },
    });
    fireEvent.click(within(dialog.closest('.ant-modal') ?? dialog).getByText('Save'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/knowledge/types')).toHaveLength(1);
    });
    const [created] = fake.find('POST', '/api/v1/knowledge/types');
    expect(created?.body).toMatchObject({
      names: { en: 'Checklist', ar: 'قائمة تحقق' },
      review_months: 12,
    });
    expect(created?.headers.get('Idempotency-Key')).toBeTruthy();

    // A built-in type: only its review interval.
    fireEvent.click(within(card).getByTestId('kb-admin-type-edit-how_to'));
    dialog = await screen.findByTestId('kb-admin-type-dialog');
    expect(within(document.body).queryByTestId('kb-admin-type-en')).toBeNull();
    fireEvent.change(within(document.body).getByTestId('kb-admin-type-months'), {
      target: { value: '24' },
    });
    fireEvent.click(within(dialog.closest('.ant-modal') ?? dialog).getByText('Save'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/knowledge/types/how_to')).toHaveLength(1);
    });
    const [changed] = fake.find('PATCH', '/api/v1/knowledge/types/how_to');
    expect(changed?.body).toEqual({ review_months: 24 });
    expect(changed?.headers.get('If-Match')).toBe('"1"');

    fireEvent.click(within(card).getByTestId('kb-admin-type-retire-custom_ab12'));
    await waitFor(() => {
      const [retired] = fake.find('PATCH', '/api/v1/knowledge/types/custom_ab12');
      expect(retired?.body).toEqual({ retired: true });
      expect(retired?.headers.get('If-Match')).toBe('"3"');
    });
  });

  it('a technician has no Knowledge tab', async () => {
    window.history.pushState({}, '', '/admin');
    api({}, fakeSession());
    render(<App />);
    await screen.findByTestId('user-name');
    expect(screen.queryByRole('tab', { name: 'Knowledge' })).toBeNull();
  });
});
