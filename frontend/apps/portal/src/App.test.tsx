import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { App } from './App';

describe('portal home page', () => {
  it('shows the product name and app name from the labels package', () => {
    render(<App />);

    expect(screen.getByRole('heading', { name: 'SupportX v2' })).toBeDefined();
    expect(screen.getByText('Self-Service Portal')).toBeDefined();
  });

  it('switches the document to right-to-left', () => {
    render(<App />);

    fireEvent.click(screen.getByRole('switch', { name: 'Right-to-left' }));

    expect(document.documentElement.dir).toBe('rtl');
  });
});
