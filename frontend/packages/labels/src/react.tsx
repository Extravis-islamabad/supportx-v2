import { useEffect, useMemo, type ReactNode } from 'react';
import { I18nextProvider } from 'react-i18next';

import { createI18n, type Locale } from './label';

export interface LabelsProviderProps {
  locale: Locale;
  children: ReactNode;
}

/** react-i18next provider with its own instance per mounted app (tests and HMR start clean). */
export function LabelsProvider({ locale, children }: LabelsProviderProps) {
  const instance = useMemo(() => createI18n(locale), []); // eslint-disable-line react-hooks/exhaustive-deps -- one instance per app; the locale effect below switches it
  useEffect(() => {
    if (instance.language !== locale) {
      void instance.changeLanguage(locale);
    }
  }, [instance, locale]);
  return <I18nextProvider i18n={instance}>{children}</I18nextProvider>;
}
