import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { isRtlLocale, LabelsProvider } from '@supportx/labels';

import { useSettings } from './settings';

/**
 * Labels in the chosen language, and the layout direction to match (rule 5d: every screen
 * works right to left). Direction is a style on the root view rather than I18nManager.forceRTL,
 * so switching language flips the layout at once, with no app restart.
 */
export function AppProviders({
  children,
  client,
}: {
  children: ReactNode;
  /** Tests pass their own, to clear its timers afterwards. */
  client?: QueryClient;
}) {
  const locale = useSettings((state) => state.locale);
  const [queryClient] = useState(
    () => client ?? new QueryClient({ defaultOptions: { queries: { retry: 1 } } }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <LabelsProvider locale={locale}>
        <View
          testID="app-root"
          style={[styles.root, { direction: isRtlLocale(locale) ? 'rtl' : 'ltr' }]}
        >
          {children}
        </View>
      </LabelsProvider>
    </QueryClientProvider>
  );
}

const styles = StyleSheet.create({ root: { flex: 1 } });
