import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  fakeConversationEntry,
  fakeIncident,
  fakeIncidentCatalogue,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-020b screens: conversation, notes, followers, counters. Names cite parity file 01.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
const ITEM = fakeIncident({ conversation_count: 3 });
const PATH = `/api/v1/incidents/${ITEM.id}`;
const TECH = '01900000-0000-7000-8000-0000000000a1';
const NOTE = fakeConversationEntry();
const PUBLIC_NOTE = fakeConversationEntry({
  id: '01900000-0000-7000-8000-0000000c0e02',
  visibility: 'public',
  body: '<p>We restarted it.</p>',
});
const REPLY = fakeConversationEntry({
  id: '01900000-0000-7000-8000-0000000c0e03',
  kind: 'reply',
  visibility: 'public',
  reply_mode: 'reply',
  recipients: { to: ['rana@demo.test'], cc: [] },
  delivery_state: 'not_sent',
  delivery_reason: 'email_channel_not_configured',
  first_response: true,
});
const COMMON = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
  'GET /api/v1/incidents/reply-templates': { body: [] },
  [`GET ${PATH}`]: { body: ITEM },
  [`GET ${PATH}/followers`]: { body: { items: [], may_manage: true, people: {} } },
  [`GET ${PATH}/conversation`]: {
    body: {
      items: [NOTE, PUBLIC_NOTE, REPLY],
      truncated: false,
      people: { [TECH]: { display_name: 'Tariq Tech', email: 'tariq@demo.test' } },
    },
  },
};

async function openConversation() {
  render(<App />);
  fireEvent.click(await screen.findByRole('tab', { name: 'Conversation (3)' }));
  return screen.findByTestId('conv-timeline');
}

describe('Conversation', () => {
  beforeEach(() => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
  });
  afterEach(() => {
    restore();
  });

  it('REQ-INC-057/061: one timeline; private and public entries look different', async () => {
    api({ routes: COMMON });
    const timeline = await openConversation();
    expect(within(timeline).getByTestId('conv-description').textContent).toContain('9:00');
    const entries = await within(timeline).findAllByTestId('conv-entry');
    expect(entries.map((e) => e.getAttribute('data-visibility'))).toEqual([
      'private',
      'public',
      'public',
    ]);
    expect(entries[0]?.textContent).toContain('Private note');
    expect(entries[0]?.textContent).toContain('Staff only');
    expect(entries[1]?.textContent).toContain('Public note');
    expect(entries[1]?.textContent).toContain('The requester can see this');
    expect(entries[0]?.textContent).toContain('Tariq Tech');
    expect(timeline.textContent).not.toMatch(/\bprivate\b|\bnot_sent\b|email_channel/);
  });

  it('WP-024 pending: a saved reply says plainly it was not sent', async () => {
    api({ routes: COMMON });
    const timeline = await openConversation();
    const notice = await within(timeline).findByTestId('conv-not-sent');
    expect(notice.textContent).toContain('Not sent: email channel not configured');
    expect(within(timeline).getByTestId('conv-first-response')).toBeDefined();
  });

  it('REQ-INC-057 AC2: each filter shows only its kind', async () => {
    api({ routes: COMMON });
    const timeline = await openConversation();
    await within(timeline).findAllByTestId('conv-entry');
    fireEvent.click(screen.getByTitle('Notes'));
    expect(
      within(timeline)
        .getAllByTestId('conv-entry')
        .map((e) => e.getAttribute('data-kind')),
    ).toEqual(['note', 'note']);
    expect(within(timeline).queryByTestId('conv-description')).toBeNull();
    fireEvent.click(screen.getByTitle('Messages'));
    expect(
      within(timeline)
        .getAllByTestId('conv-entry')
        .map((e) => e.getAttribute('data-kind')),
    ).toEqual(['reply']);
    fireEvent.click(screen.getByTitle('System'));
    expect(within(timeline).queryAllByTestId('conv-entry')).toHaveLength(0);
    expect(timeline.textContent).toContain('No system messages yet');
  });

  it('REQ-INC-061: a note is private unless chosen public, sent once with an Idempotency-Key', async () => {
    const fake = api({
      routes: {
        ...COMMON,
        [`POST ${PATH}/conversation`]: {
          status: 201,
          body: { entry: NOTE, not_notified: [], people: {} },
        },
      },
    });
    await openConversation();
    fireEvent.click(screen.getByTestId('conv-add-note'));
    const composer = await screen.findByTestId('conv-composer');
    expect(within(composer).getByTestId<HTMLInputElement>('conv-visibility-private').checked).toBe(
      true,
    );
    const editor = await within(composer).findByTestId('conv-editor');
    // Typing into ProseMirror in jsdom is unreliable; Tiptap hangs its editor on the DOM node.
    const tiptap = (
      editor as HTMLElement & { editor: { commands: { insertContent: (h: string) => void } } }
    ).editor;
    act(() => {
      tiptap.commands.insertContent('Checked the logs');
    });
    await waitFor(() => {
      expect(screen.getByTestId<HTMLButtonElement>('conv-send').disabled).toBe(false);
    });
    fireEvent.click(screen.getByTestId('conv-send'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/conversation`)).toHaveLength(1);
    });
    const [call] = fake.find('POST', `${PATH}/conversation`);
    expect(call?.body).toMatchObject({ kind: 'note', visibility: 'private' });
    expect(call?.headers.get('Idempotency-Key')).toBeTruthy();
  });

  it('REQ-INC-061 AC3: making a note public asks first', async () => {
    const fake = api({
      routes: {
        ...COMMON,
        [`PATCH ${PATH}/conversation/${NOTE.id}`]: { body: { ...NOTE, visibility: 'public' } },
      },
    });
    const timeline = await openConversation();
    const note = (await within(timeline).findAllByTestId('conv-entry'))[0];
    if (note === undefined) throw new Error('no note');
    fireEvent.click(within(note).getByTestId('conv-switch-visibility'));
    expect(await screen.findByText('Make this note public?')).toBeDefined();
    expect(fake.find('PATCH', `${PATH}/conversation/${NOTE.id}`)).toHaveLength(0);
    const popup = screen.getByText('Make this note public?').closest<HTMLElement>('.ant-popover');
    if (popup === null) throw new Error('no confirmation');
    fireEvent.click(within(popup).getByRole('button', { name: 'Make public' }));
    await waitFor(() => {
      expect(fake.find('PATCH', `${PATH}/conversation/${NOTE.id}`)).toHaveLength(1);
    });
    const [call] = fake.find('PATCH', `${PATH}/conversation/${NOTE.id}`);
    expect(call?.headers.get('If-Match')).toBe('"1"');
  });

  it('reply buttons say why they are disabled', async () => {
    api({
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: {
          body: {
            ...ITEM,
            conversation_actions: ITEM.conversation_actions.map((a) =>
              a.action === 'reply' ? { ...a, allowed: false, reason: 'out_of_scope' } : a,
            ),
          },
        },
      },
    });
    await openConversation();
    const reply = screen.getByTestId('conv-reply').querySelector('button');
    expect(reply?.disabled).toBe(true);
    expect(screen.getByTestId<HTMLButtonElement>('conv-add-note').disabled).toBe(false);
  });
});

describe('Followers', () => {
  beforeEach(() => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
  });
  afterEach(() => {
    restore();
  });

  it('REQ-INC-151: someone following after a hand-over is shown with why and their access', async () => {
    const fake = api({
      routes: {
        ...COMMON,
        [`GET ${PATH}/followers`]: {
          body: {
            items: [
              {
                user_id: TECH,
                reason: 'handed_over',
                grants_access: true,
                since: '2026-10-24T09:00:00Z',
                removable: true,
              },
            ],
            may_manage: true,
            people: { [TECH]: { display_name: 'Tariq Tech', email: 'tariq@demo.test' } },
          },
        },
        [`DELETE ${PATH}/followers/${TECH}`]: {
          body: { items: [], may_manage: true, people: {} },
        },
      },
    });
    render(<App />);
    const card = await screen.findByTestId('inc-followers');
    const row = await within(card).findByTestId('inc-follower');
    expect(row.textContent).toContain('Tariq Tech');
    expect(row.textContent).toContain('Kept after handing it over');
    expect(row.textContent).toContain('Sees it by following');
    expect(row.textContent).not.toContain('handed_over');
    fireEvent.click(within(row).getByTestId('inc-follower-remove'));
    await waitFor(() => {
      expect(fake.find('DELETE', `${PATH}/followers/${TECH}`)).toHaveLength(1);
    });
  });
});

describe('Personal counters', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/incidents');
  });
  afterEach(() => {
    restore();
  });

  it('REQ-INC-128: counters show live counts and open the matching view', async () => {
    const fake = api({
      routes: {
        ...COMMON,
        'GET /api/v1/incidents/views': { body: [{ view: 'open', count: 1, capped: false }] },
        'GET /api/v1/incidents': {
          body: { items: [], has_more: false, next_cursor: null, estimated_total: 0, people: {} },
        },
        'GET /api/v1/incidents/counters': {
          body: [
            { counter: 'my_overdue', count: 2, capped: false },
            { counter: 'my_due_today', count: 0, capped: false },
            { counter: 'waiting_on_me', count: 4, capped: false },
            { counter: 'updated_by_others', count: 1, capped: false },
            { counter: 'unassigned_in_my_groups', count: 3, capped: false },
          ],
        },
      },
    });
    render(<App />);
    const waiting = await screen.findByTestId('inc-counter-waiting_on_me');
    await waitFor(() => {
      expect(waiting.textContent).toBe('4Waiting on me');
    });
    fireEvent.click(waiting);
    await waitFor(() => {
      const last = fake.find('GET', '/api/v1/incidents').at(-1);
      expect(last?.url.searchParams.get('view')).toBe('waiting_on_me');
    });
    expect(waiting.getAttribute('aria-pressed')).toBe('true');
  });
});
