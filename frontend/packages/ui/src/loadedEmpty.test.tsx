import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { loadedEmpty } from './loadedEmpty';
import { renderUi } from './test/render';

describe('loadedEmpty (QA fix-round, 2026-11-10)', () => {
  it('says nothing while the list loads, and the empty text once its answer is in', () => {
    const view = renderUi(<div>{loadedEmpty(true, 'No incidents in this view')}</div>);
    expect(screen.queryByText('No incidents in this view')).toBeNull();
    view.unmount();
    renderUi(<div>{loadedEmpty(false, 'No incidents in this view')}</div>);
    expect(screen.getByTestId('empty-text').textContent).toBe('No incidents in this view');
  });
});
