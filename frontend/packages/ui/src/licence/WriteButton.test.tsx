import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { renderUi } from '../test/render';
import { WriteButton } from './WriteButton';

describe('WriteButton', () => {
  it('D-155: disabled, it says why on hover, and the reason is reachable by keyboard', async () => {
    renderUi(
      <WriteButton disabled whyDisabled="Choose a start and an end first." data-testid="add">
        Add downtime
      </WriteButton>,
    );
    const wrapper = screen.getByTestId('disabled-why');
    expect(wrapper.getAttribute('tabindex')).toBe('0');
    expect(screen.getByTestId<HTMLButtonElement>('add').disabled).toBe(true);
    fireEvent.mouseOver(wrapper);
    expect(await screen.findByText('Choose a start and an end first.')).toBeDefined();
  });

  it('enabled, it is a plain button', () => {
    renderUi(
      <WriteButton whyDisabled="unused" data-testid="add">
        Add downtime
      </WriteButton>,
    );
    expect(screen.queryByTestId('disabled-why')).toBeNull();
    expect(screen.getByTestId<HTMLButtonElement>('add').disabled).toBe(false);
  });
});
