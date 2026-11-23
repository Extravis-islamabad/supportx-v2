import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
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
    expect(opener.getAttribute('aria-label')).toBe('Move to… REL-1');
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

  // WP-046b S3b (lane C): the optional props; without them the board is as above.
  it('says "N of M" when a column holds more than it shows, and renders its footer', () => {
    renderUi(
      <StageBoard
        columns={[
          { key: 'build', title: 'Build', count: 5 },
          { key: 'testing', title: 'Testing', count: 1 },
        ]}
        cards={cards}
        renderCard={(card) => <span>{card.name}</span>}
        onMove={vi.fn()}
        label="Board"
        footer={(column) => <button type="button">More in {column.title}</button>}
      />,
    );
    expect(screen.getByTestId('stage-board-count-build').textContent).toBe('1 of 5');
    expect(screen.getByTestId('stage-board-count-testing').textContent).toBe('1');
    expect(screen.getByRole('button', { name: 'More in Build' })).toBeTruthy();
  });

  it('a column a card cannot go to is reachable by keyboard, says why, and never moves', async () => {
    const onMove = vi.fn(() => Promise.resolve(null));
    renderUi(
      <StageBoard
        columns={columns}
        cards={cards}
        renderCard={(card) => <span>{card.name}</span>}
        onMove={onMove}
        label="Board"
        whyNot={(_card, column) => (column === 'deployment' ? 'Testing must pass first.' : null)}
      />,
    );
    fireEvent.click(screen.getByTestId('stage-board-move-r1'));
    const menu = (await screen.findAllByRole('menu')).at(-1);
    if (menu === undefined) throw new Error('no menu');
    const unavailable = within(menu).getByTestId('stage-board-unavailable-deployment');
    // Not antd's disabled (skipped by the arrows): an enabled item that says why in its name.
    const item = unavailable.closest('[role="menuitem"]');
    expect(item?.className).not.toMatch(/disabled/);
    expect(item?.getAttribute('aria-disabled')).not.toBe('true');
    expect(unavailable.textContent).toContain('Testing must pass first.');
    fireEvent.click(unavailable);
    await waitFor(() => {
      expect(screen.getByTestId('stage-board-refusal').textContent).toBe(
        'Testing must pass first.',
      );
    });
    // And the drop path refuses the same way.
    const dataTransfer = transfer();
    fireEvent.dragStart(screen.getByTestId('stage-board-card-r1'), { dataTransfer });
    const target = screen.getByTestId('stage-board-column-deployment');
    fireEvent.dragOver(target, { dataTransfer });
    fireEvent.drop(target, { dataTransfer });
    expect(onMove).not.toHaveBeenCalled();
  });

  it("focus returns to the card's Move to, or to the column when the card has left", async () => {
    const onMove = vi.fn(() => Promise.resolve(null));
    // One mounted board whose cards change, as a refetch changes them (no remount).
    let drop: () => void = () => undefined;
    function Harness() {
      const [shown, setShown] = useState(cards);
      drop = () => {
        setShown(cards.filter((c) => c.id !== 'r1'));
      };
      return (
        <StageBoard
          columns={columns}
          cards={shown}
          renderCard={(card) => <span>{card.name}</span>}
          onMove={onMove}
          label="Board"
        />
      );
    }
    renderUi(<Harness />);
    fireEvent.click(screen.getByTestId('stage-board-move-r2'));
    const menu = (await screen.findAllByRole('menu')).at(-1);
    if (menu === undefined) throw new Error('no menu');
    fireEvent.click(within(menu).getByText('Build'));
    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByTestId('stage-board-move-r2'));
    });
    // As in the app: the move settles (focus on its Move to), then the refetch drops the card.
    fireEvent.click(screen.getByTestId('stage-board-move-r1'));
    const again = (await screen.findAllByRole('menu')).at(-1);
    if (again === undefined) throw new Error('no menu');
    fireEvent.click(within(again).getByText('Deployment'));
    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByTestId('stage-board-move-r1'));
    });
    act(() => {
      drop();
    });
    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByTestId('stage-board-heading-deployment'));
    });
  });
});
