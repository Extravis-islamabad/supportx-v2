import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
  fakeKbArticle,
  type FakeRoute,
} from '@supportx/api-client/testing';
import { setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../App';
import { consoleApi, fakeSession } from '../../test/api';
import { rememberTab } from '../incidents/tabs';

// WP-033 session 4 (D-121): knowledge in the incident's editors and side panel.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const ME = '01900000-0000-7000-8000-000000000101';
const ITEM = fakeIncident({ conversation_count: 0 });
const PATH = `/api/v1/incidents/${ITEM.id}`;
const ARTICLE = fakeKbArticle();
const ROW = {
  id: ARTICLE.id,
  display_id: 'KB-1',
  topic_id: ARTICLE.topic_id,
  type_code: 'how_to',
  language: 'en',
  title: 'Reset your VPN token',
  status: 'published',
  review_on: null,
  updated_at: '2026-11-02T08:00:00Z',
  owner_id: ARTICLE.owner_id,
  expired: false,
  withdrawn: false,
  review_due: false,
};
const APPLIED = {
  article_id: ARTICLE.id,
  display_id: 'KB-1',
  title: 'Reset your VPN token',
  language: 'en',
  fallback: false,
  html: '<p>Open the portal and reset the token.</p>',
  visible_to_requester: false,
  images_not_copied: [],
};
const RECORD_ARTICLES = `GET /api/v1/knowledge/records/incident/${ITEM.id}/articles`;
const COMMON: Record<string, FakeRoute> = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/organization/departments': { body: [] },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
  'GET /api/v1/incidents/reply-templates': { body: [] },
  [`GET ${PATH}/followers`]: { body: { items: [], may_manage: true, people: {} } },
  [`GET ${PATH}/conversation`]: { body: { items: [], truncated: false, people: {} } },
  [`GET ${PATH}/automation`]: { body: [] },
  'GET /api/v1/knowledge/topics': {
    body: [
      {
        id: ARTICLE.topic_id,
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
      },
    ],
  },
  'GET /api/v1/knowledge/types': {
    body: [
      { code: 'how_to', names: {}, builtin: true, retired: false, review_months: 12, version: 1 },
    ],
  },
  'GET /api/v1/knowledge/articles': { body: [ROW] },
  [RECORD_ARTICLES]: { body: { items: [], restricted: 0 } },
};

function api(routes: Record<string, FakeRoute>, item = ITEM) {
  const fake = consoleApi({
    me: fakeSession({ roles: ['tenant_admin', 'technician'] }),
    routes: { ...COMMON, [`GET ${PATH}`]: { body: item }, ...routes },
  });
  restore = fake.restore;
  return fake;
}

async function openComposer(kind: 'reply' | 'note') {
  render(<App />);
  fireEvent.click(await screen.findByRole('tab', { name: /Conversation/ }));
  await screen.findByTestId('conv-timeline');
  if (kind === 'reply') {
    const reply = screen.getByTestId('inc-op-reply').querySelector('button');
    if (reply === null) throw new Error('no reply button');
    fireEvent.click(reply);
  } else {
    fireEvent.click(screen.getByTestId('conv-add-note'));
  }
  return screen.findByTestId('conv-composer');
}

async function pick(action: 'content' | 'link') {
  // The reply editor may open in a dialog of its own: look for the button on the whole page.
  // The Knowledge card in the properties panel (on every tab since D-124) has a picker of its
  // own: take the editor's, the one outside the card.
  const open = await waitFor(() => {
    const found = screen
      .queryAllByTestId('kb-picker-open')
      .filter((button) => button.closest('[data-testid="kb-card"]') === null)
      .at(-1);
    if (found === undefined) throw new Error('no picker in the editor yet');
    return found;
  });
  fireEvent.click(open);
  const drawers = await screen.findAllByTestId('kb-picker');
  const drawer = drawers.at(-1);
  if (drawer === undefined) throw new Error('no picker drawer');
  fireEvent.click(await within(drawer).findByTestId(`kb-picker-${action}-KB-1`));
}

describe('Knowledge in the reply editor (REQ-KB-063)', () => {
  beforeEach(() => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    localStorage.clear();
  });

  it('warns before a public insert when the server says the requester cannot read it', async () => {
    const fake = api({
      [`GET /api/v1/knowledge/articles/${ARTICLE.id}/apply-check`]: {
        body: { visible_to_requester: false },
      },
      [`POST /api/v1/knowledge/articles/${ARTICLE.id}/apply`]: { body: APPLIED },
    });
    await openComposer('reply');
    await pick('content');
    expect(await screen.findByTestId('kb-picker-warning')).toBeDefined();
    const [check] = fake.find('GET', `/api/v1/knowledge/articles/${ARTICLE.id}/apply-check`);
    expect(check?.url.searchParams.get('audience')).toBe('public');
    expect(fake.find('POST', `/api/v1/knowledge/articles/${ARTICLE.id}/apply`)).toHaveLength(0);
    const dialog = screen.getByTestId('kb-picker-warning').closest<HTMLElement>('.ant-modal');
    if (dialog === null) throw new Error('the warning is not a dialog');
    fireEvent.click(within(dialog).getByText('Insert content'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/knowledge/articles/${ARTICLE.id}/apply`)).toHaveLength(1);
    });
    await waitFor(() => {
      expect(screen.getByTestId('conv-editor').textContent).toContain(
        'Open the portal and reset the token.',
      );
    });
  });

  it('no warning when the server says the requester can read it', async () => {
    const fake = api({
      [`GET /api/v1/knowledge/articles/${ARTICLE.id}/apply-check`]: {
        body: { visible_to_requester: true },
      },
      [`POST /api/v1/knowledge/articles/${ARTICLE.id}/apply`]: {
        body: { ...APPLIED, visible_to_requester: true },
      },
    });
    await openComposer('reply');
    await pick('link');
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/knowledge/articles/${ARTICLE.id}/apply`)).toHaveLength(1);
    });
    expect(screen.queryByTestId('kb-picker-warning')).toBeNull();
    const [call] = fake.find('POST', `/api/v1/knowledge/articles/${ARTICLE.id}/apply`);
    expect(call?.body).toMatchObject({ mode: 'link', audience: 'public', record_id: ITEM.id });
    await waitFor(() => {
      expect(screen.getByTestId('conv-editor').textContent).toContain('KB-1 Reset your VPN token');
    });
  });

  it('a private note asks nothing: staff only read it', async () => {
    const fake = api({
      [`POST /api/v1/knowledge/articles/${ARTICLE.id}/apply`]: {
        body: { ...APPLIED, visible_to_requester: null },
      },
    });
    await openComposer('note');
    await pick('content');
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/knowledge/articles/${ARTICLE.id}/apply`)).toHaveLength(1);
    });
    expect(fake.find('GET', `/api/v1/knowledge/articles/${ARTICLE.id}/apply-check`)).toHaveLength(
      0,
    );
    const [call] = fake.find('POST', `/api/v1/knowledge/articles/${ARTICLE.id}/apply`);
    expect(call?.body).toMatchObject({ audience: 'private' });
  });
});

describe("The incident's Knowledge card (D-121)", () => {
  beforeEach(() => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    localStorage.clear();
    // The card sits in the Details tab's side column: start there (D-081).
    rememberTab(ME, 'details');
  });

  it('lists readable articles, counts the others, and refetches live on a link', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    let items: unknown[] = [];
    const fake = api({
      [RECORD_ARTICLES]: () => ({ body: { items, restricted: 2 } }),
    });
    render(<App />);
    const card = await screen.findByTestId('kb-card');
    expect(await within(card).findByTestId('kb-card-restricted')).toBeDefined();
    expect(within(card).getByTestId('kb-card-restricted').textContent).toBe(
      '2 restricted articles',
    );
    items = [
      { link_id: 'l1', source: 'insert', linked_at: '2026-11-02T09:00:00Z', article: ARTICLE },
    ];
    const before = fake.find('GET', RECORD_ARTICLES.slice(4)).length;
    act(() => {
      realtime.publish(`:wi:${ITEM.id}`, { type: 'knowledge.link.saved', ids: [ITEM.id] });
    });
    await waitFor(() => {
      expect(fake.find('GET', RECORD_ARTICLES.slice(4)).length).toBeGreaterThan(before);
    });
    const line = await within(card).findByTestId('kb-card-item-KB-1');
    expect(line.textContent).toContain('Reset your VPN token');
    expect(line.textContent).toContain('Used in a reply');
    expect(line.textContent).not.toMatch(/insert|created_from/);
  });

  it('saves the resolution as knowledge with the last topic pre-selected, then names personal data', async () => {
    localStorage.setItem(`sx.kb.lastTopic.${ME}`, ARTICLE.topic_id);
    rememberTab(ME, 'details');
    const resolved = fakeIncident({
      conversation_count: 0,
      status: 'resolved',
      status_category: 'resolved',
      resolution: '<p>Called Sara on +966 50 123 4567.</p>',
    });
    const fake = api(
      {
        'POST /api/v1/knowledge/articles/from-record': {
          status: 201,
          body: {
            article: { ...ARTICLE, drafts: { en: ARTICLE.published.en }, published: {} },
            personal_data: [{ field: 'body', kind: 'phone' }],
          },
        },
      },
      resolved,
    );
    render(<App />);
    fireEvent.click(await screen.findByTestId('kb-card-save'));
    const dialog = await screen.findByTestId('kb-save-dialog');
    expect((await within(document.body).findAllByText('Network')).length).toBeGreaterThan(0);
    fireEvent.click(within(dialog.closest('.ant-modal') ?? dialog).getByText('Create draft'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/knowledge/articles/from-record')).toHaveLength(1);
    });
    const [call] = fake.find('POST', '/api/v1/knowledge/articles/from-record');
    expect(call?.body).toMatchObject({ topic_id: ARTICLE.topic_id, record_id: ITEM.id });
    expect(call?.headers.get('Idempotency-Key')).toBeTruthy();
    await screen.findByText('Check for personal data');
    expect(document.body.textContent).toContain('A phone number in the text');
  });
});
