import { useTranslation } from 'react-i18next';

import type { LabelInput, LabelParams } from './label';

/** `t(key, params)` bound to the current locale; re-renders when the language changes. */
export function useLabels(): (key: LabelInput, params?: LabelParams) => string {
  const { t } = useTranslation();
  return (key, params) => t(key, params);
}
