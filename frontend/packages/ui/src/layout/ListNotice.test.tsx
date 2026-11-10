import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { renderUi } from '../test/render';
import { ListNotice } from './ListPage';

describe('ListNotice', () => {
  it('is one small line that stays closed for the session once closed, until its text changes', () => {
    const first = renderUi(
      <ListNotice testId="n" dismissKey="incidents.view.open">
        All open: 42 shown
      </ListNotice>,
    );
    expect(screen.getByTestId('n').getAttribute('role')).toBe('status');
    fireEvent.click(screen.getByTestId('n-close'));
    expect(screen.queryByTestId('n')).toBeNull();
    first.unmount();
    const again = renderUi(
      <ListNotice testId="n" dismissKey="incidents.view.open">
        All open: 42 shown
      </ListNotice>,
    );
    expect(screen.queryByTestId('n')).toBeNull(); // still closed
    again.unmount();
    renderUi(
      <ListNotice testId="n" dismissKey="incidents.view.open">
        All open: 43 shown
      </ListNotice>,
    );
    expect(screen.getByTestId('n')).toBeDefined(); // a new count shows again
  });
});
