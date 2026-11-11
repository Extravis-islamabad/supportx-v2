import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { renderUi } from '../test/render';
import { CellText } from './CellText';

// jsdom has no layout: a cell is "cut" when its content is wider than its box.
function sized(cell: HTMLElement, content: number, box: number) {
  Object.defineProperty(cell, 'scrollWidth', { configurable: true, value: content });
  Object.defineProperty(cell, 'clientWidth', { configurable: true, value: box });
}

describe('CellText', () => {
  it('cuts at the text’s own end: its own direction and its own ellipsis', () => {
    renderUi(<CellText>Nadia Iqbal</CellText>);
    const cell = screen.getByText('Nadia Iqbal');
    expect(cell.tagName).toBe('BDI');
    expect(cell.getAttribute('dir')).toBe('auto');
    expect(cell.className).toContain('sx-cell-text');
  });

  it('QA fix-round: cut text shows the whole of it in a tooltip; text that fits shows none', async () => {
    const long = 'Network and access, second floor';
    const view = renderUi(<CellText>{long}</CellText>);
    const cell = screen.getByText(long);
    sized(cell, 300, 120);
    fireEvent.mouseEnter(cell);
    expect((await screen.findByRole('tooltip')).textContent).toBe(long);
    view.unmount();

    renderUi(<CellText>Short</CellText>);
    const fits = screen.getByText('Short');
    sized(fits, 40, 120);
    fireEvent.mouseEnter(fits);
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(screen.queryByRole('tooltip')).toBeNull();
  });
});
