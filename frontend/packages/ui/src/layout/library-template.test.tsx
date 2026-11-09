import { fireEvent, screen, within } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { renderUi } from '../test/render';
import { LibraryPage, type LibraryGroup } from './LibraryPage';

const GROUPS: LibraryGroup[] = [
  {
    key: 'incidents',
    label: 'Incidents',
    items: [
      { key: 'a', title: 'Open by priority', searchText: 'Open by priority', testId: 'item-a' },
      { key: 'b', title: 'Ageing', searchText: 'Ageing of open incidents', testId: 'item-b' },
    ],
  },
  { key: 'changes', label: 'Changes', items: [], empty: 'Change reports come later.' },
];

function Harness({ onStar }: { onStar?: (key: string, starred: boolean) => void }) {
  const [search, setSearch] = useState('');
  return (
    <LibraryPage
      header={<h1>Reports</h1>}
      groups={GROUPS}
      search={search}
      onSearch={setSearch}
      searchLabel="Search reports"
      favourites={new Set(['b'])}
      onStar={onStar}
    />
  );
}

// D-147 template D: search and favourites on top, one tab per module, "All" first.
describe('template D (library page)', () => {
  it('puts search and favourites above one tab per module, All first, with counts', () => {
    renderUi(<Harness onStar={vi.fn()} />);
    const page = screen.getByTestId('library');
    const search = screen.getByTestId('library-search');
    const favourites = screen.getByTestId('library-favourites');
    const tabs = screen.getByTestId('library-tabs');
    // Order on the page: search, favourites, tabs.
    expect(
      search.compareDocumentPosition(favourites) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      favourites.compareDocumentPosition(tabs) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(within(favourites).getByText('Ageing')).toBeTruthy();
    const names = within(tabs)
      .getAllByRole('tab')
      .map((tab) => tab.textContent);
    expect(names).toEqual(['All 2', 'Incidents 2', 'Changes 0']);
    expect(page).toBeTruthy();
  });

  it('keeps a module with nothing yet, saying why', () => {
    renderUi(<Harness />);
    const changes = screen.getByTestId('library-group-changes');
    expect(within(changes).getByText('Change reports come later.')).toBeTruthy();
    // No empty list around the text (axe aria-required-children, visual matrix 42703327955).
    expect(changes.querySelector('[role="list"]')).toBeNull();
    expect(
      screen.getByTestId('library-group-incidents').querySelector('[role="list"]'),
    ).not.toBeNull();
  });

  it('filters every group as you type and says when nothing matches', () => {
    renderUi(<Harness />);
    fireEvent.change(screen.getByLabelText('Search reports'), { target: { value: 'ageing' } });
    expect(screen.queryByTestId('item-a')).toBeNull();
    expect(screen.getAllByTestId('item-b').length).toBeGreaterThan(0);
    // A group with no match is left out of "All" while searching.
    expect(screen.queryByTestId('library-group-changes')).toBeNull();
    fireEvent.change(screen.getByLabelText('Search reports'), { target: { value: 'zzz' } });
    expect(screen.getAllByText('Nothing matches your search.').length).toBeGreaterThan(0);
  });

  it('stars and unstars with a labelled, pressed button', () => {
    const onStar = vi.fn();
    renderUi(<Harness onStar={onStar} />);
    const star = screen.getAllByTestId('item-a-star')[0];
    expect(star?.getAttribute('aria-pressed')).toBe('false');
    if (star !== undefined) fireEvent.click(star);
    expect(onStar).toHaveBeenCalledWith('a', true);
    const unstar = screen.getAllByTestId('item-b-star')[0];
    expect(unstar?.getAttribute('aria-pressed')).toBe('true');
  });

  it('shows views of one server-searched list as tabs, without "All" or counts', () => {
    const onSearch = vi.fn();
    renderUi(
      <LibraryPage
        header={null}
        testId="kb"
        search="vpn"
        onSearch={onSearch}
        searchLabel="Search articles"
        searchOnServer
        withAll={false}
        tab="drafts"
        groups={[
          { key: 'published', label: 'Published', items: [], count: null, content: null },
          {
            key: 'drafts',
            label: 'Drafts',
            items: [],
            count: null,
            content: <p>the drafts table</p>,
          },
        ]}
      />,
    );
    const names = within(screen.getByTestId('kb-tabs'))
      .getAllByRole('tab')
      .map((tab) => tab.textContent);
    expect(names).toEqual(['Published', 'Drafts']);
    // The server searched: the body is shown as given, with no "nothing matches" here.
    expect(screen.getByText('the drafts table')).toBeTruthy();
    expect(screen.queryByText('Nothing matches your search.')).toBeNull();
  });
});
