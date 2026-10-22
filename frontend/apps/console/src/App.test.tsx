import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';

describe('console home page', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('{}', { status: 200 }))),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows the product name and app name from the labels package', () => {
    render(<App />);

    expect(screen.getByRole('heading', { name: 'SupportX v2' })).toBeDefined();
    expect(screen.getByText('Technician Console')).toBeDefined();
  });

  it('switches the document to right-to-left', () => {
    render(<App />);

    fireEvent.click(screen.getByRole('switch', { name: 'Right-to-left' }));

    expect(document.documentElement.dir).toBe('rtl');
  });

  it('shows the live API status on the home page', async () => {
    render(<App />);

    expect(await screen.findByText('API online')).toBeDefined();
  });
});
