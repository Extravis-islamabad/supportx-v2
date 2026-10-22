import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Locale } from '@supportx/labels';
import { AppearanceProvider } from '@supportx/ui';

import { ApiStatus } from './ApiStatus';

function renderStatus(locale: Locale = 'en') {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <AppearanceProvider initialLocale={locale}>
        <ApiStatus />
      </AppearanceProvider>
    </QueryClientProvider>,
  );
}

describe('ApiStatus', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('calls the health endpoint through the same-origin proxy', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response('{}', { status: 200 })));
    vi.stubGlobal('fetch', fetchMock);

    renderStatus();

    expect(await screen.findByText('API online')).toBeDefined();
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/health', expect.anything());
  });

  it('shows a checking label until the first answer arrives', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => undefined)),
    );

    renderStatus();

    expect(screen.getByRole('status').textContent).toBe('Checking API…');
  });

  it('shows offline when the API answers with an error status', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('', { status: 503 }))),
    );

    renderStatus();

    expect(await screen.findByText('API offline')).toBeDefined();
  });

  it('renders the status label in Arabic (RTL)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('{}', { status: 200 }))),
    );

    renderStatus('ar');

    expect(await screen.findByText('الواجهة البرمجية متصلة')).toBeDefined();
    expect(document.documentElement.dir).toBe('rtl');
  });

  it('shows offline when the API cannot be reached', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))),
    );

    renderStatus();

    expect(await screen.findByText('API offline')).toBeDefined();
  });
});
