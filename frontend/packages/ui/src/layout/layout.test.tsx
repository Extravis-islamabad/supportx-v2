import { fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { renderUi } from '../test/render';
import { ActionBar, type RecordAction } from './ActionBar';
import { AlertStrip } from './AlertStrip';
import { HeaderActions } from './HeaderActions';
import { NoticeStack } from './NoticeStack';
import { FORM_MAX_WIDTH, PageColumn } from './PageColumn';
import { SectionNav } from './SectionNav';

// D-124: buttons for the available everyday actions (at most four, the most useful ones),
// every action in "More actions" in its fixed order, destructive ones last and confirmed.

const action = (key: string, extra: Partial<RecordAction> = {}): RecordAction => ({
  key,
  label: key,
  allowed: true,
  primary: true,
  onClick: vi.fn(),
  testId: `a-${key}`,
  ...extra,
});

async function menu(): Promise<HTMLElement> {
  fireEvent.click(screen.getByTestId('bar-more'));
  const menus = await screen.findAllByRole('menu');
  const found = menus.at(-1);
  if (found === undefined) throw new Error('no menu');
  return found;
}

describe('ActionBar', () => {
  it('gives the four best-ranked available actions a button, in the fixed order', () => {
    renderUi(
      <ActionBar
        testId="bar"
        actions={[
          action('assign', { rank: 4 }),
          action('start', { rank: 3 }),
          action('wait', { rank: 7 }),
          action('resolve', { rank: 1 }),
          action('close', { rank: 6 }),
          action('reopen', { allowed: false, whyNot: 'Not now.', rank: 2 }),
        ]}
      />,
    );
    const buttons = screen
      .getAllByRole('button')
      .map((b) => b.getAttribute('data-testid'))
      .filter((id) => id !== 'bar-more');
    expect(buttons).toEqual(['a-assign', 'a-start', 'a-resolve', 'a-close']);
    // The most useful one is primary, wherever it sits.
    expect(screen.getByTestId('a-resolve').className).toContain('ant-btn-primary');
    expect(screen.getByTestId('a-assign').className).not.toContain('ant-btn-primary');
  });

  it('quiet: the same buttons in the same order, none primary (an open composer holds it)', () => {
    const actions = [
      action('assign', { rank: 4 }),
      action('reply', {
        rank: 1,
        variants: [{ key: 'reply_all', label: 'Reply all', onClick: vi.fn() }],
      }),
      action('resolve', { rank: 2 }),
    ];
    const ids = () =>
      screen
        .getAllByRole('button')
        .map((b) => b.getAttribute('data-testid'))
        .filter((id) => id !== null && id !== 'bar-more');
    const { unmount } = renderUi(<ActionBar testId="bar" actions={actions} />);
    const loud = ids();
    expect(document.querySelectorAll('.ant-btn-primary').length).toBeGreaterThan(0);
    unmount();
    renderUi(<ActionBar testId="bar" actions={actions} quiet />);
    expect(ids()).toEqual(loud);
    expect(document.querySelectorAll('.ant-btn-primary')).toHaveLength(0);
  });

  it("QA10V-03: a split button's chevron is named after its action", () => {
    const reply = action('reply', {
      label: 'Reply',
      variants: [{ key: 'reply_all', label: 'Reply all', onClick: vi.fn() }],
    });
    renderUi(<ActionBar testId="bar" actions={[reply]} />);
    const chevron = within(screen.getByTestId('a-reply-more')).getByRole('button');
    expect(chevron.getAttribute('aria-label')).toBe('More options: Reply');
  });

  it('QA bug 7: a split button on the bar is not repeated in More, nor are its variants', async () => {
    renderUi(
      <ActionBar
        testId="bar"
        actions={[
          action('reply', {
            rank: 0,
            variants: [
              { key: 'forward', label: 'Forward', onClick: () => undefined, testId: 'a-forward' },
            ],
          }),
          action('assign', { rank: 1 }),
          action('note', { primary: false }),
        ]}
      />,
    );
    const items = within(await menu()).getAllByRole('menuitem');
    const ids = items.map((i) => i.getAttribute('data-testid'));
    expect(ids).not.toContain('a-reply-menu');
    expect(screen.queryByTestId('a-forward-menu')).toBeNull();
    expect(ids).toContain('a-assign-menu'); // a plain bar button keeps its entry ("Also above")
    expect(ids).toContain('a-note-menu');
  });

  it('QA10-P4-24: menu items that are also buttons say so, in the fixed order', async () => {
    renderUi(
      <ActionBar
        testId="bar"
        max={1}
        actions={[
          action('assign', { rank: 2 }),
          action('resolve', { rank: 1 }),
          action('note', { primary: false }),
        ]}
      />,
    );
    const items = within(await menu()).getAllByRole('menuitem');
    expect(items.map((i) => i.getAttribute('data-testid'))).toEqual([
      'a-assign-menu',
      'a-resolve-menu',
      'a-note-menu',
    ]);
    const marked = (testId: string) =>
      screen.getByTestId(testId).querySelector('[data-also-above]') !== null;
    expect(marked('a-resolve-menu')).toBe(true);
    expect(screen.getByTestId('a-resolve-menu').textContent).toContain('Also above');
    expect(marked('a-assign-menu')).toBe(false);
    expect(marked('a-note-menu')).toBe(false);
  });

  it('lists every action in the menu, unavailable ones disabled with the reason, destructive last', async () => {
    renderUi(
      <ActionBar
        testId="bar"
        actions={[
          action('delete', { danger: true, confirm: 'Delete it?' }),
          action('assign'),
          action('reopen', { allowed: false, whyNot: 'Not possible now.' }),
        ]}
      />,
    );
    const items = within(await menu()).getAllByRole('menuitem');
    expect(items.map((i) => i.getAttribute('data-testid'))).toEqual([
      'a-assign-menu',
      'a-reopen-menu',
      'a-delete-menu',
    ]);
    const reopen = screen.getByTestId('a-reopen-menu');
    expect(reopen.getAttribute('aria-disabled')).toBe('true');
    expect(reopen.textContent).toContain('Not possible now.');
  });

  it('QA6-INC-02: unavailable actions sit under their reason, said once, after the available ones', async () => {
    const why = 'Not possible in the current status.';
    renderUi(
      <ActionBar
        testId="bar"
        actions={[
          action('close', { allowed: false, whyNot: why }),
          action('assign'),
          action('reopen', { allowed: false, whyNot: why }),
          action('resume', { allowed: false, whyNot: why }),
        ]}
      />,
    );
    const list = await menu();
    const items = within(list).getAllByRole('menuitem');
    expect(items.map((i) => i.getAttribute('data-testid'))).toEqual([
      'a-assign-menu',
      'a-close-menu',
      'a-reopen-menu',
      'a-resume-menu',
    ]);
    // One heading for the three; the reason is not repeated on screen beside each entry.
    const headings = [...list.querySelectorAll('.ant-dropdown-menu-item-group-title')];
    expect(headings.map((h) => h.textContent)).toEqual([why]);
  });

  it('asks before a destructive action that gives a question, once', async () => {
    const remove = action('delete', {
      danger: true,
      confirm: 'Delete it?',
      confirmOk: 'Delete',
      confirmCancel: 'Keep',
    });
    renderUi(<ActionBar testId="bar" actions={[remove]} />);
    fireEvent.click(within(await menu()).getByTestId('a-delete-menu'));
    expect(remove.onClick).not.toHaveBeenCalled();
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getAllByText('Delete it?').length).toBeGreaterThan(0);
    expect(within(dialog).queryByRole('button', { name: 'Cancel' })).toBeNull();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));
    expect(remove.onClick).toHaveBeenCalledTimes(1);
  });

  it('read-only licence: every action is disabled with the read-only reason', async () => {
    const assign = action('assign');
    renderUi(<ActionBar testId="bar" actions={[assign]} />, { licence: { writable: false } });
    expect(screen.queryByTestId('a-assign')).toBeNull();
    const entry = within(await menu()).getByTestId('a-assign-menu');
    expect(entry.getAttribute('aria-disabled')).toBe('true');
    expect(entry.textContent).toContain('Not available in read-only mode.');
    fireEvent.click(entry);
    expect(assign.onClick).not.toHaveBeenCalled();
  });
});

describe('SectionNav', () => {
  it('is a nav of links, never a tablist, and marks the open section', () => {
    const go = vi.fn();
    renderUi(
      <SectionNav
        label="Administration"
        active="roles"
        onNavigate={go}
        testId="sections"
        items={[
          { key: 'people', label: 'People', path: '/admin/people' },
          { key: 'roles', label: 'Roles', path: '/admin/roles' },
        ]}
      />,
    );
    // Sections are pages: links in a nav (axe aria-required-children failed on the tab overflow).
    expect(screen.queryByRole('tablist')).toBeNull();
    expect(screen.getByRole('navigation', { name: 'Administration' })).toBeDefined();
    const roles = screen.getByRole('link', { name: 'Roles' });
    expect(roles.getAttribute('aria-current')).toBe('page');
    expect(screen.getByRole('link', { name: 'People' }).getAttribute('href')).toBe('/admin/people');
    fireEvent.click(screen.getByRole('link', { name: 'People' }));
    expect(go).toHaveBeenCalledWith('/admin/people');
  });
});

describe('NoticeStack', () => {
  const Notice = ({ text }: { text: string | null }) =>
    text === null ? null : <div role="status">{text}</div>;

  it('one notice shows alone; several keep the first and say how many more', () => {
    const one = renderUi(
      <NoticeStack testId="notices">
        <Notice text="Offline" />
        <Notice text={null} />
      </NoticeStack>,
    );
    expect(screen.queryByTestId('notices-toggle')).toBeNull();
    one.unmount();
    renderUi(
      <NoticeStack testId="notices">
        <Notice text={null} />
        <Notice text="Scanner down" />
        <Notice text="Choose visibility" />
        <Notice text="MFA due" />
      </NoticeStack>,
    );
    expect(screen.getByTestId('notices').textContent).toContain('2 more notices');
    const hidden = screen.getByText('Choose visibility').closest('[data-notices-collapsed]');
    expect(hidden?.getAttribute('data-notices-collapsed')).toBe('true');
    fireEvent.click(screen.getByTestId('notices-toggle'));
    expect(screen.getByTestId('notices-toggle').getAttribute('aria-expanded')).toBe('true');
    expect(hidden?.getAttribute('data-notices-collapsed')).toBe('false');
  });

  it('D-147: one strip, "N more" on its line, dismissed until a notice is added', () => {
    const { rerender } = renderUi(
      <NoticeStack testId="notices">
        <Notice text="Scanner down" />
        <Notice text="MFA due" />
      </NoticeStack>,
    );
    const strip = screen.getByTestId('notices');
    // The toggle sits in the same row as the notice, not on a line of its own.
    expect(screen.getByTestId('notices-toggle').parentElement).toBe(
      screen.getByText('Scanner down').closest('[data-notices-collapsed]')?.parentElement,
    );
    fireEvent.click(screen.getByTestId('notices-dismiss'));
    expect(strip.hidden).toBe(true);
    rerender(
      <NoticeStack testId="notices">
        <Notice text="Scanner down" />
        <Notice text="MFA due" />
        <Notice text="Licence expires" />
      </NoticeStack>,
    );
    expect(screen.getByTestId('notices').hidden).toBe(false); // a new notice brings it back
  });

  it('QA10-P3-10: a dismissed notice that goes and comes back, or a remount, keeps it hidden', () => {
    window.sessionStorage.clear();
    const view = renderUi(
      <NoticeStack testId="notices">
        <Notice text="Scanner down" />
        <Notice text="MFA due" />
      </NoticeStack>,
    );
    fireEvent.click(screen.getByTestId('notices-dismiss'));
    // Another page: the MFA reminder is not shown there, then is again.
    view.rerender(
      <NoticeStack testId="notices">
        <Notice text="Scanner down" />
      </NoticeStack>,
    );
    expect(screen.getByTestId('notices').hidden).toBe(true);
    view.rerender(
      <NoticeStack testId="notices">
        <Notice text="Scanner down" />
        <Notice text="MFA due" />
      </NoticeStack>,
    );
    expect(screen.getByTestId('notices').hidden).toBe(true);
    // The strip mounted again (the layout re-rendered from scratch): still hidden.
    view.unmount();
    renderUi(
      <NoticeStack testId="notices">
        <Notice text="Scanner down" />
      </NoticeStack>,
    );
    expect(screen.getByTestId('notices').hidden).toBe(true);
    window.sessionStorage.clear();
  });

  it('an empty box never takes the visible place; a critical notice does (announcements.spec)', () => {
    const Empty = () => <div />;
    const view = renderUi(
      <NoticeStack testId="notices">
        <Empty />
        <Notice text="MFA due" />
        <div>
          <div data-notice-critical="true">Critical: network down</div>
        </div>
      </NoticeStack>,
    );
    expect(screen.getByTestId('notices').textContent).toContain('1 more notice');
    // The critical notice is the one left showing; the other one is hidden while collapsed.
    const critical = screen.getByText('Critical: network down').closest('[data-notice-extra]');
    expect(critical).toBeNull();
    expect(screen.getByText('MFA due').closest('[data-notice-extra]')).not.toBeNull();
    view.unmount();
    renderUi(
      <NoticeStack testId="notices">
        <Empty />
        <Notice text="Scanner down" />
        <Notice text="MFA due" />
      </NoticeStack>,
    );
    // Without a critical one, the first notice with text shows (not the empty box).
    expect(screen.getByText('Scanner down').closest('[data-notice-extra]')).toBeNull();
    expect(screen.getByText('MFA due').closest('[data-notice-extra]')).not.toBeNull();
  });
});

describe('AlertStrip', () => {
  it('one alert is a strip; several collapse into "N alerts · View"', () => {
    const one = renderUi(
      <AlertStrip testId="strip" alerts={[{ key: 'a', type: 'warning', message: 'First' }]} />,
    );
    expect(screen.getByTestId('strip').textContent).toContain('First');
    one.unmount();
    renderUi(
      <AlertStrip
        testId="strip"
        alerts={[
          { key: 'a', type: 'warning', message: 'First' },
          { key: 'b', type: 'error', message: 'Second' },
          { key: 'c', type: 'info', message: 'Third' },
        ]}
      />,
    );
    expect(screen.getByTestId('strip').textContent).toContain('3 alerts');
    expect(screen.queryByText('Second')).toBeNull();
    fireEvent.click(screen.getByTestId('strip-toggle'));
    expect(screen.getByText('Second')).toBeDefined();
  });
});

describe('D-147 template C: header actions', () => {
  it('shows at most three buttons with the primary last, the rest in More', async () => {
    const opened: string[] = [];
    renderUi(
      <HeaderActions
        testId="head"
        primary={<button type="button">New</button>}
        buttons={[
          { key: 'a', node: <button type="button">Export</button> },
          {
            key: 'b',
            node: <button type="button">Import</button>,
            overflow: { key: 'b', label: 'Import', onClick: () => opened.push('b'), testId: 'b' },
          },
        ]}
        more={[{ key: 'c', label: 'Recent jobs', onClick: () => opened.push('c'), testId: 'c' }]}
      />,
    );
    const head = screen.getByTestId('head');
    const visible = within(head)
      .getAllByRole('button')
      .map((b) => b.textContent.trim());
    expect(visible).toEqual(['Export', 'More', 'New']); // three places: Import moved into More
    fireEvent.click(screen.getByTestId('head-more'));
    fireEvent.click(await screen.findByTestId('b'));
    expect(opened).toEqual(['b']);
  });

  it('never drops a button that has no menu form', () => {
    renderUi(
      <HeaderActions
        testId="head2"
        primary={<button type="button">New</button>}
        buttons={[
          { key: 'a', node: <button type="button">Export</button> },
          { key: 'b', node: <button type="button">Switch</button> },
        ]}
        more={[{ key: 'c', label: 'Recent jobs', onClick: () => undefined }]}
      />,
    );
    const shown = within(screen.getByTestId('head2'))
      .getAllByRole('button')
      .map((b) => b.textContent.trim());
    expect(shown).toEqual(['Export', 'Switch', 'More', 'New']);
  });
});

describe('D-147: page widths', () => {
  it('a form runs at most 960 px, with its help column beside it; a list takes the width', () => {
    renderUi(
      <>
        <PageColumn kind="form" testId="form" aside={<p>Help</p>}>
          <p>Fields</p>
        </PageColumn>
        <PageColumn kind="list" testId="list">
          <p>Rows</p>
        </PageColumn>
      </>,
    );
    // The test window is narrow: the help column goes below the form, which keeps its cap.
    expect(screen.getByTestId('form').style.maxWidth).toBe(`${String(FORM_MAX_WIDTH)}px`);
    expect(screen.getByTestId('form').querySelector('aside')?.textContent).toBe('Help');
    expect(screen.getByTestId('list').style.width).toBe('100%');
  });

  it('a full-width page keeps its aside (lane A, #351: it was dropped silently)', () => {
    renderUi(
      <PageColumn kind="list" testId="wide" aside={<p>Suggestions</p>}>
        <p>Fields</p>
      </PageColumn>,
    );
    expect(screen.getByTestId('wide').style.width).toBe('100%');
    expect(screen.getByTestId('wide').querySelector('aside')?.textContent).toBe('Suggestions');
  });
});

describe('D-147: one close button per line', () => {
  it('a notice with its own close keeps it, and the strip shows no second one', () => {
    renderUi(
      <NoticeStack testId="notices">
        <div>
          <div className="ant-alert">
            Announcement
            <button type="button" className="ant-alert-close-icon">
              x
            </button>
          </div>
        </div>
        <div>MFA due</div>
      </NoticeStack>,
    );
    expect(screen.queryByTestId('notices-dismiss')).toBeNull();
    expect(screen.getByTestId('notices-toggle')).toBeDefined();
  });
});
