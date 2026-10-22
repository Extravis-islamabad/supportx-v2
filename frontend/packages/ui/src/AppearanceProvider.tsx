import { App as AntApp, ConfigProvider, theme } from 'antd';
import { useEffect, useMemo, useState, type ReactNode } from 'react';

import { isRtlLocale, type Locale } from '@supportx/labels';

import { AppearanceContext, type Appearance, type Direction, type ThemeMode } from './appearance';
import { brandTokens } from './tokens';

export interface AppearanceProviderProps {
  children: ReactNode;
  initialMode?: ThemeMode;
  initialLocale?: Locale;
}

/** Wires Ant Design's ConfigProvider to light/dark theme tokens, text direction and locale. */
export function AppearanceProvider({
  children,
  initialMode = 'light',
  initialLocale = 'en',
}: AppearanceProviderProps) {
  const [mode, setMode] = useState<ThemeMode>(initialMode);
  const [locale, setLocaleState] = useState<Locale>(initialLocale);
  const [direction, setDirection] = useState<Direction>(isRtlLocale(initialLocale) ? 'rtl' : 'ltr');

  useEffect(() => {
    document.documentElement.dir = direction;
    document.documentElement.lang = locale;
  }, [direction, locale]);

  const appearance = useMemo<Appearance>(
    () => ({
      mode,
      direction,
      locale,
      setMode,
      setDirection,
      setLocale: (next) => {
        setLocaleState(next);
        setDirection(isRtlLocale(next) ? 'rtl' : 'ltr');
      },
    }),
    [mode, direction, locale],
  );

  return (
    <AppearanceContext.Provider value={appearance}>
      <ConfigProvider
        direction={direction}
        theme={{
          algorithm: mode === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
          token: brandTokens,
        }}
      >
        <AntApp>{children}</AntApp>
      </ConfigProvider>
    </AppearanceContext.Provider>
  );
}
