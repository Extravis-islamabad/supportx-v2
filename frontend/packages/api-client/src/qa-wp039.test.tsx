import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it } from 'vitest';

import { queryKeys } from './keys';
import { useLogout } from './session';
import { fakeApi, fakeSession, problem } from './testing';

// WP-039 QA (~/Desktop/qa-wp039/QA-REPORT.md), one test per finding.

describe('BUG-03: at the idle limit the screen signs out even when the server already did', () => {
  let restore: () => void = () => undefined;
  afterEach(() => {
    restore();
  });

  it('clears the local session when logout answers 401 (the session already ended)', async () => {
    const fake = fakeApi({
      'POST /api/v1/auth/logout': { status: 401, body: problem(401, 'unauthenticated') },
    });
    restore = fake.restore;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(queryKeys.session, fakeSession());
    function wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const { result } = renderHook(() => useLogout(), { wrapper });
    await act(async () => {
      await result.current();
    });
    expect(client.getQueryData(queryKeys.session)).toBeNull();
  });
});
