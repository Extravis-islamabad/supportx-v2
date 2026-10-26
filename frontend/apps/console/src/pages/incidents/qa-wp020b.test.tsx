import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  fakeConversationEntry,
  fakeIncident,
  fakeIncidentCatalogue,
  problem,
} from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';
import { TYPING_HEARTBEAT_MS, TYPING_IDLE_MS, TYPING_SHOWN_MS, useTypingSignal } from './typing';
import { rememberTab } from './tabs';

// WP-020b QA findings on the incident screens (Desktop/qa-wp020b/QA-REPORT.md) and the product
// owner's answers (D-081). Each test is named after its finding and failed before the fix.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
const ME = '01900000-0000-7000-8000-000000000101';
const TARIQ = '01900000-0000-7000-8000-0000000000a1';
const ITEM = fakeIncident({ conversation_count: 2, group_id: 'g-a' });
const PATH = `/api/v1/incidents/${ITEM.id}`;
const PRIVATE = fakeConversationEntry();
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
const NO_FOLLOWERS = { items: [], may_manage: true, people: {} };
const COMMON = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': {
    body: [{ id: 'g-a', name: 'Service Desk', member_ids: [] }],
  },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
  'GET /api/v1/incidents/reply-templates': { body: [] },
  [`GET ${PATH}`]: { body: ITEM },
  [`GET ${PATH}/followers`]: { body: NO_FOLLOWERS },
  [`GET ${PATH}/conversation`]: {
    body: {
      items: [PRIVATE, REPLY],
      truncated: false,
      people: { [TARIQ]: { display_name: 'Tariq Technician', email: 'tariq@demo.test' } },
    },
  },
};

async function openRecord() {
  render(<App />);
  return screen.findByTestId('inc-heading');
}

async function openConversation() {
  await openRecord();
  fireEvent.click(await screen.findByRole('tab', { name: /^Conversation/ }));
  return screen.findByTestId('conv-timeline');
}

function selectorOf(select: HTMLElement): Element {
  const found = select.querySelector('.ant-select-selector');
  if (found === null) throw new Error('not an Ant Design Select');
  return found;
}

beforeEach(() => {
  window.history.pushState({}, '', `/incidents/${ITEM.id}`);
  localStorage.clear();
});
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
  vi.useRealTimers();
});

describe('QA WP-020b on the incident screens', () => {
  it('BUG-01: conversation tags use readable tones, never Ant Design preset colours', async () => {
    api({ routes: COMMON });
    const timeline = await openConversation();
    await within(timeline).findAllByTestId('conv-entry');
    expect(
      timeline.querySelector('.ant-tag-warning, .ant-tag-success, .ant-tag-purple'),
    ).toBeNull();
    expect(timeline.querySelector('.ant-tag-blue')).toBeNull();
    const tones = [...timeline.querySelectorAll('[data-tone]')].map((e) =>
      e.getAttribute('data-tone'),
    );
    expect(tones).toEqual(expect.arrayContaining(['warning', 'purple', 'success']));
  });

  it('BUG-04: the typing signal repeats while someone keeps typing, and stops when they pause', () => {
    vi.useFakeTimers();
    const send = vi.fn();
    const { result } = renderHook(() => useTypingSignal('r1', 'note', send));
    for (let second = 0; second < 10; second += 1) {
      act(() => {
        result.current.typed();
        vi.advanceTimersByTime(1000);
      });
    }
    const starts = send.mock.calls.filter(([, state]) => state === 'start').length;
    expect(starts).toBeGreaterThanOrEqual(3); // at 0 s, about 3 s, 6 s, 9 s
    expect(TYPING_HEARTBEAT_MS).toBeLessThan(TYPING_SHOWN_MS); // the receiver never expires it
    act(() => {
      vi.advanceTimersByTime(TYPING_IDLE_MS + 10);
    });
    expect(send.mock.calls.at(-1)?.[1]).toBe('stop');
  });

  it('BUG-06: a counter view says which view is active and how many it leaves out', async () => {
    window.history.pushState({}, '', '/incidents');
    api({
      routes: {
        ...COMMON,
        'GET /api/v1/incidents/views': {
          body: [
            { view: 'open', count: 6, capped: false },
            { view: 'all', count: 8, capped: false },
          ],
        },
        'GET /api/v1/incidents': {
          body: { items: [], has_more: false, next_cursor: null, estimated_total: 0, people: {} },
        },
        'GET /api/v1/incidents/counters': {
          body: [
            { counter: 'my_overdue', count: 0, capped: false },
            { counter: 'my_due_today', count: 0, capped: false },
            { counter: 'waiting_on_me', count: 3, capped: false },
            { counter: 'updated_by_others', count: 0, capped: false },
            { counter: 'unassigned_in_my_groups', count: 0, capped: false },
          ],
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-counter-waiting_on_me'));
    await waitFor(() => {
      const notice = screen.getByTestId('inc-view-notice');
      expect(notice.textContent).toContain('View “Waiting on me”: 3 shown.');
      expect(notice.textContent).toContain('5 other incidents you can see are not in this view.');
    });
    expect(screen.getByTestId('inc-show-all')).toBeDefined();
  });

  it('BUG-07: an open composer picks up reply template changes live', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    const fake = api({ routes: COMMON });
    await openConversation();
    fireEvent.click(screen.getByTestId('conv-add-note'));
    await screen.findByTestId('conv-composer');
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/incidents/reply-templates').length).toBeGreaterThan(0);
    });
    const before = fake.find('GET', '/api/v1/incidents/reply-templates').length;
    act(() => {
      realtime.publish(':broadcast', { type: 'work_items.reply_templates_changed', ids: [] });
    });
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/incidents/reply-templates').length).toBe(before + 1);
    });
  });

  it('BUG-08: the follower picker shows the results of what was typed, not an older search', async () => {
    api({
      routes: {
        ...COMMON,
        [`GET ${PATH}/mentionable`]: async (call) => {
          const search = call.url.searchParams.get('search') ?? '';
          const everyone = [
            { id: 'u1', display_name: 'Adel Admin', email: 'adel@demo.test', can_see: true },
            { id: TARIQ, display_name: 'Tariq Technician', email: 'tech@demo.test', can_see: true },
          ];
          if (search === '') {
            await new Promise((resolve) => setTimeout(resolve, 300)); // the slow first answer
            return { body: everyone };
          }
          return { body: everyone.filter((p) => p.display_name.toLowerCase().includes(search)) };
        },
      },
    });
    await openRecord();
    fireEvent.click(screen.getByRole('tab', { name: 'Details' }));
    const picker = await screen.findByTestId('inc-follower-add');
    const input = picker.querySelector('input');
    if (input === null) throw new Error('no input');
    fireEvent.focus(input);
    fireEvent.mouseDown(selectorOf(picker));
    fireEvent.change(input, { target: { value: 'tar' } });
    await new Promise((resolve) => setTimeout(resolve, 500));
    const options = [...document.querySelectorAll('.ant-select-item-option')].map(
      (o) => o.textContent,
    );
    expect(options).toHaveLength(1);
    expect(options[0]).toContain('Tariq Technician');
  });

  it('BUG-09: removing a follower who would lose access asks first; others go at once', async () => {
    const fake = api({
      routes: {
        ...COMMON,
        [`GET ${PATH}/followers`]: {
          body: {
            items: [
              {
                user_id: TARIQ,
                reason: 'handed_over',
                grants_access: true,
                since: '2026-10-24T09:00:00Z',
                removable: true,
              },
              {
                user_id: 'u3',
                reason: 'self',
                grants_access: false,
                since: '2026-10-24T09:00:00Z',
                removable: true,
              },
            ],
            may_manage: true,
            people: {
              [TARIQ]: { display_name: 'Tariq Technician', email: 'tech@demo.test' },
              u3: { display_name: 'Chen', email: 'chen@demo.test' },
            },
          },
        },
        [`DELETE ${PATH}/followers/${TARIQ}`]: { body: NO_FOLLOWERS },
        [`DELETE ${PATH}/followers/u3`]: {
          body: {
            items: [
              {
                user_id: TARIQ,
                reason: 'handed_over',
                grants_access: true,
                since: '2026-10-24T09:00:00Z',
                removable: true,
              },
            ],
            may_manage: true,
            people: { [TARIQ]: { display_name: 'Tariq Technician', email: 'tech@demo.test' } },
          },
        },
      },
    });
    await openRecord();
    fireEvent.click(screen.getByRole('tab', { name: 'Details' }));
    const [, chen] = await screen.findAllByTestId('inc-follower');
    if (chen === undefined) throw new Error('two followers expected');
    // Someone who follows by choice goes at once (no access to lose).
    fireEvent.click(within(chen).getByTestId('inc-follower-remove'));
    await waitFor(() => {
      expect(fake.find('DELETE', `${PATH}/followers/u3`)).toHaveLength(1);
    });
    const [tariq] = await screen.findAllByTestId('inc-follower');
    if (tariq === undefined) throw new Error('Tariq expected');
    fireEvent.click(within(tariq).getByTestId('inc-follower-remove'));
    expect(
      await screen.findByText('Tariq Technician sees this incident only by following it.', {
        exact: false,
      }),
    ).toBeDefined();
    expect(fake.find('DELETE', `${PATH}/followers/${TARIQ}`)).toHaveLength(0);
    const popup = screen
      .getByText('Tariq Technician sees this incident only by following it.', { exact: false })
      .closest<HTMLElement>('.ant-popover');
    if (popup === null) throw new Error('no confirmation');
    fireEvent.click(within(popup).getByRole('button', { name: 'Remove' }));
    await waitFor(() => {
      expect(fake.find('DELETE', `${PATH}/followers/${TARIQ}`)).toHaveLength(1);
    });
  });

  it('BUG-10: the reply menu opens on click, not hover, and closes after a choice', async () => {
    api({ routes: COMMON });
    await openConversation();
    const arrow = screen.getByTestId('conv-reply-more').querySelector('button');
    if (arrow === null) throw new Error('no arrow');
    fireEvent.mouseEnter(arrow);
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(document.querySelector('.ant-dropdown:not(.ant-dropdown-hidden)')).toBeNull();
    fireEvent.click(arrow);
    fireEvent.click(await screen.findByText('Reply to all'));
    expect((await screen.findByTestId('conv-composer')).textContent).toContain('Reply to all');
    // Closed or closing (jsdom never finishes Ant Design's leave animation).
    await waitFor(() => {
      const open = [...document.querySelectorAll('.ant-dropdown')].filter(
        (d) => !d.className.includes('hidden') && !d.className.includes('-leave'),
      );
      expect(open).toHaveLength(0);
    });
  });

  it('C2: an invalid address is named, with no second "required" message', async () => {
    api({
      routes: {
        ...COMMON,
        [`POST ${PATH}/conversation`]: {
          status: 422,
          body: problem(422, 'validation_failed', {
            errors: [
              {
                field: 'body.to',
                code: 'invalid_email',
                message_key: 'errors.field.invalid_email',
                params: { addresses: 'vendor-at-example' },
              },
            ],
          }),
        },
      },
    });
    await openConversation();
    fireEvent.click(screen.getByTestId('conv-add-note'));
    const editor = await screen.findByTestId<
      HTMLElement & { editor: { commands: { insertContent: (h: string) => void } } }
    >('conv-editor');
    act(() => {
      editor.editor.commands.insertContent('x');
    });
    fireEvent.click(screen.getByTestId('conv-send'));
    const errors = await screen.findByTestId('conv-errors');
    expect(errors.textContent).toContain('vendor-at-example');
  });

  it('C4: one hidden incident is said in the singular', async () => {
    window.history.pushState({}, '', '/incidents');
    api({
      routes: {
        ...COMMON,
        'GET /api/v1/incidents/views': {
          body: [
            { view: 'open', count: 7, capped: false },
            { view: 'all', count: 8, capped: false },
          ],
        },
        'GET /api/v1/incidents': {
          body: { items: [], has_more: false, next_cursor: null, estimated_total: 0, people: {} },
        },
        'GET /api/v1/incidents/counters': { body: [] },
      },
    });
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId('inc-view-notice').textContent).toContain(
        '1 other incident you can see is not in this view.',
      );
    });
  });

  it('C5: the automatic tag and "by" are separate words in history', async () => {
    api({
      routes: {
        ...COMMON,
        [`GET ${PATH}/history`]: {
          body: {
            items: [
              {
                change_id: 'c1',
                kind: 'status',
                occurred_at: '2026-10-24T09:00:00Z',
                actor_type: 'user',
                actor_id: ME,
                actor_name: 'Amal Admin',
                source: 'ui',
                reason: null,
                automation: { kind: 'auto_move' },
                audit_entry_id: null,
                changes: [{ field: 'status', old: 'new', new: 'assigned' }],
              },
            ],
            next_cursor: null,
            people: {},
          },
        },
      },
    });
    await openRecord();
    fireEvent.click(screen.getByRole('tab', { name: /^History/ }));
    const entry = await screen.findByTestId('inc-history-entry');
    expect(entry.textContent).toMatch(/Automatic by Amal Admin/);
  });

  it('C6: the group name keeps its brackets together in either reading direction', async () => {
    api({ routes: COMMON });
    await openRecord();
    const people = screen.getByTestId('inc-people');
    const isolated = [...people.querySelectorAll('bdi')].map((b) => b.textContent);
    expect(isolated).toContain('(Service Desk)');
  });

  it('D-081: mentioning someone who cannot see the incident warns before sending', async () => {
    const fake = api({
      routes: {
        ...COMMON,
        [`POST ${PATH}/conversation`]: {
          status: 201,
          body: { entry: PRIVATE, not_notified: [TARIQ], people: {} },
        },
      },
    });
    await openConversation();
    fireEvent.click(screen.getByTestId('conv-add-note'));
    const editor = await screen.findByTestId<
      HTMLElement & { editor: { commands: { insertContent: (h: unknown) => void } } }
    >('conv-editor');
    act(() => {
      editor.editor.commands.insertContent({
        type: 'mention',
        attrs: { id: TARIQ, label: 'Tariq Technician', canSee: false },
      });
    });
    fireEvent.click(screen.getByTestId('conv-send'));
    const warning = await screen.findByTestId('conv-mention-warning');
    expect(warning.textContent).toContain(
      "Tariq Technician can't see this incident and won't be notified.",
    );
    expect(fake.find('POST', `${PATH}/conversation`)).toHaveLength(0);
    fireEvent.click(within(warning).getByRole('button', { name: 'Send anyway' }));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/conversation`)).toHaveLength(1);
    });
    // The marker is for the composer only; the server gets clean editor markup.
    const sent = fake.find('POST', `${PATH}/conversation`)[0]?.body as { body: string };
    expect(sent.body).not.toContain('data-can-see');
  });

  it('D-081: the record opens on Conversation, then on the tab this user used last', async () => {
    api({ routes: COMMON });
    const { unmount } = render(<App />);
    await screen.findByTestId('inc-heading');
    expect(screen.getByRole('tab', { name: /^Conversation/ }).getAttribute('aria-selected')).toBe(
      'true',
    );
    fireEvent.click(screen.getByRole('tab', { name: 'Details' }));
    unmount();
    render(<App />);
    await screen.findByTestId('inc-heading');
    expect(screen.getByRole('tab', { name: 'Details' }).getAttribute('aria-selected')).toBe('true');
    // Kept per user: another person on this browser starts on Conversation.
    rememberTab('someone-else', 'history');
    expect(localStorage.getItem(`sx.incident.tab.${ME}`)).toBe('details');
  });
});
