import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { renderUi } from '../test/render';
import { CellText } from './CellText';

describe('CellText', () => {
  it('cuts at the text’s own end: its own direction, its own ellipsis, the whole text as the title', () => {
    renderUi(<CellText title="Nadia Iqbal">Nadia Iqbal</CellText>);
    const cell = screen.getByText('Nadia Iqbal');
    expect(cell.tagName).toBe('BDI');
    expect(cell.getAttribute('dir')).toBe('auto');
    expect(cell.className).toContain('sx-cell-text');
    expect(cell.getAttribute('title')).toBe('Nadia Iqbal');
  });
});
