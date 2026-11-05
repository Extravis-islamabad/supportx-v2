import '../src/polyfills';

import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { setClientApp } from '@supportx/api-client';

import { AppProviders } from '../src/AppProviders';
import { useSettings } from '../src/settings';

// Every call says it comes from the mobile app: history records it as UI, not API (D-145).
setClientApp('mobile');

export default function RootLayout() {
  const loaded = useSettings((state) => state.loaded);
  const load = useSettings((state) => state.load);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <SafeAreaProvider>
      <AppProviders>
        <StatusBar style="auto" />
        {/* Screens draw their own titles: native headers would not follow the in-app direction. */}
        {loaded ? <Stack screenOptions={{ headerShown: false }} /> : null}
      </AppProviders>
    </SafeAreaProvider>
  );
}
