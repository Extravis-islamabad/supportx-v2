import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';

import { AppearanceProvider } from '@supportx/ui';

import { HomePage } from './HomePage';

export function App() {
  // One cache per mounted app (not module-level), so tests and HMR start clean.
  const [queryClient] = useState(() => new QueryClient());
  return (
    <QueryClientProvider client={queryClient}>
      <AppearanceProvider>
        <HomePage />
      </AppearanceProvider>
    </QueryClientProvider>
  );
}
