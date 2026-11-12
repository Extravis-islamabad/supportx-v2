import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { renderUi } from '../test/render';
import { StageBoard, type BoardCard } from './StageBoard';

// REQ-REL-056 (WP-058b S5b): cards in columns, moved by dragging or from the keyboard's "Move to"
// menu; a refused move leaves the card and says why, in a live region.

const columns = [
  { key: 'build', title: 'Build' },
  { key: 'testing', title: 'Testing' },
  { key: 'deployment', title: 'Deployment' },
];
const cards: BoardCard[] = [
  { id: 'r1', column: 'build', name: 'REL-1' },
  { id: 'r2', column: 'testing', name: 'REL-2' },
];

function board(onMove: (card: BoardCard, column: string) => Promise<string | null>) {
  return renderUi(
    <StageBoard
      columns={columns}
      cards={cards}
      renderCard={(card) => <span>{card.name}</span>}
      onMove={onMove}
      label="Releases by stage"
    />,
  );
}

/** A DataTransfer stand-in: jsdom has none. */
function transfer() {
  const data = new Map<string, string>();
  return {
    setData: (type: string, value: string) => data.set(type, value),
    getData: (type: string) => data.get(type) ?? '',
    effectAllowed: 'all',
    dropEffect: 'move',
  };
}

describe('StageBoard', () => {
  it('lists each column with its cards and count', () => {
    board(vi.fn());
    const build = screen.getByTestId('stage-board-column-build');
    expect(within(build).getByText('REL-1')).toBeTruthy();
    expect(within(build).getByText('1')).toBeTruthy();
    expect(within(screen.getByTestId('stage-board-column-deployment')).getByText('0')).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Releases by stage' })).toBeTruthy();
  });

  it('moves a card from the keyboard menu, offering only the other columns', async () => {
    const onMove = vi.fn(() => Promise.resolve(null));
    board(onMove);
    const opener = screen.getByTestId('stage-board-move-r1');
    expect(opener.getAttribute('aria-label')).toBe('Move REL-1 to…');
    fireEvent.click(opener);
    const menus = await screen.findAllByRole('menu');
    const menu = menus.at(-1);
    if (menu === undefined) throw new Error('no menu');
    expect(within(menu).queryByText('Build')).toBeNull(); // where it is already
    fireEvent.click(within(menu).getByText('Deployment'));
    await waitFor(() => {
      expect(onMove).toHaveBeenCalledWith(cards[0], 'deployment');
    });
  });

  it('AC1: a refused drop leaves the card and says why', async () => {
    const onMove = vi.fn(() => Promise.resolve('Testing must pass first.'));
    board(onMove);
    const dataTransfer = transfer();
    fireEvent.dragStart(screen.getByTestId('stage-board-card-r1'), { dataTransfer });
    const target = screen.getByTestId('stage-board-column-deployment');
    fireEvent.dragOver(target, { dataTransfer });
    fireEvent.drop(target, { dataTransfer });
    await waitFor(() => {
      expect(screen.getByTestId('stage-board-refusal').textContent).toBe(
        'Testing must pass first.',
      );
    });
    expect(onMove).toHaveBeenCalledWith(cards[0], 'deployment');
    // The card is still where it was: the page moves it only when the move is made.
    expect(within(screen.getByTestId('stage-board-column-build')).getByText('REL-1')).toBeTruthy();
  });

  it('a drop on its own column does nothing', () => {
    const onMove = vi.fn(() => Promise.resolve(null));
    board(onMove);
    const dataTransfer = transfer();
    fireEvent.dragStart(screen.getByTestId('stage-board-card-r1'), { dataTransfer });
    fireEvent.drop(screen.getByTestId('stage-board-column-build'), { dataTransfer });
    expect(onMove).not.toHaveBeenCalled();
  });
});
