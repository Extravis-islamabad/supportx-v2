import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeApi } from '@supportx/api-client/testing';
import type { Locale } from '@supportx/labels';
import { AppearanceProvider } from '@supportx/ui';

import { ApiStatus } from './ApiStatus';

function renderStatus(locale: Locale = 'en') {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <AppearanceProvider initialLocale={locale} initialMode="light">
        <ApiStatus />
      </AppearanceProvider>
    </QueryClientProvider>,
  );
}

describe('ApiStatus', () => {
  let restore: () => void = () => undefined;
  afterEach(() => {
    restore();
  });

  it('calls the health endpoint and shows online', async () => {
    const fake = fakeApi({ 'GET /api/v1/health': { body: { status: 'ok', version: '1' } } });
    restore = fake.restore;
    renderStatus();
    expect(await screen.findByText('API online')).toBeDefined();
    expect(fake.find('GET', '/api/v1/health')).toHaveLength(1);
  });

  it('shows a checking label until the first answer arrives', () => {
    const fake = fakeApi({ 'GET /api/v1/health': () => new Promise(() => undefined) });
    restore = fake.restore;
    renderStatus();
    expect(screen.getByText('Checking API…')).toBeDefined();
  });

  it('shows offline when the API is down, in Arabic', async () => {
    const fake = fakeApi({ 'GET /api/v1/health': { status: 503 } });
    restore = fake.restore;
    renderStatus('ar');
    expect(await screen.findByText('الواجهة البرمجية غير متصلة')).toBeDefined();
  });
});
