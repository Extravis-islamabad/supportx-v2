import { QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactNode } from 'react';

import type { Locale } from '@supportx/labels';

import type { ThemeMode } from '../theme';

import { AppearanceProvider } from '../AppearanceProvider';
import { createQueryClient, ErrorReporterProvider } from '../errors';
import { LicenceContext, type Licence } from '../licence/context';

const NO_LICENCE: Licence = { entitlements: null, has: () => true, writable: true, isAdmin: false };

/** Render inside the real providers (theme, labels, error reporter) with a given licence. */
export function renderUi(
  ui: ReactNode,
  {
    locale = 'en',
    licence = NO_LICENCE,
    mode = 'light',
  }: { locale?: Locale; licence?: Partial<Licence>; mode?: ThemeMode } = {},
) {
  const client = createQueryClient();
  return render(
    <QueryClientProvider client={client}>
      <AppearanceProvider initialLocale={locale} initialMode={mode}>
        <ErrorReporterProvider>
          <LicenceContext.Provider value={{ ...NO_LICENCE, ...licence }}>
            {ui}
          </LicenceContext.Provider>
        </ErrorReporterProvider>
      </AppearanceProvider>
    </QueryClientProvider>,
  );
}
