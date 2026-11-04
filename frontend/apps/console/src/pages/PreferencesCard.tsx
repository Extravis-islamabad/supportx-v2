import { Card, Flex, Segmented, Select, Space, Typography } from 'antd';
import { useMemo } from 'react';

import {
  useSetPreference,
  type MeResponse,
  type PersonalPreferenceChange,
} from '@supportx/api-client';
import { reportError, systemMode, TEXT_SCALES, useAppearance, useLabel } from '@supportx/ui';

// WP-042 (REQ-ADM-058, 059, 062): theme, text size and regional formats in one place, saved
// with the person so they follow them to every device and apply at once on every open tab.
// "Default" clears a choice: the site's or tenant's value then applies, read by the server.

type User = MeResponse['user'];
const THEMES = ['light', 'dark', 'high_contrast', 'system'] as const;
const WEEK_STARTS = ['monday', 'sunday', 'saturday'] as const;
const DATE_FORMATS = ['dd/mm/yyyy', 'mm/dd/yyyy', 'yyyy-mm-dd', 'dd.mm.yyyy'] as const;
const TIME_FORMATS = ['24h', '12h'] as const;
const DIGITS = ['western', 'arabic_indic'] as const;
const DEFAULT = '__default';

export function PreferencesCard({ user }: { user: User }) {
  const t = useLabel();
  const { intlLocale, setMode, setTextScale } = useAppearance();
  const save = useSetPreference(user.id);
  const chosen = new Set(user.chosen ?? []);
  const percent = useMemo(
    () => new Intl.NumberFormat(intlLocale, { style: 'percent' }),
    [intlLocale],
  );
  const set = (change: PersonalPreferenceChange) => {
    save.mutate(change, { onError: reportError });
  };

  const regional = <F extends 'week_start' | 'date_format' | 'time_format' | 'digits'>(
    field: F,
    choices: readonly NonNullable<User[F]>[],
    label: (value: NonNullable<User[F]>) => string,
  ) => (
    <Space direction="vertical" size={4} style={{ flex: '1 1 200px' }}>
      <Typography.Text id={`pref-${field}-label`}>{t(`preferences.${field}`)}</Typography.Text>
      <Select<string>
        aria-labelledby={`pref-${field}-label`}
        data-testid={`pref-${field}`}
        value={chosen.has(field) ? user[field] : DEFAULT}
        onChange={(next) => {
          set({
            field,
            value: next === DEFAULT ? null : next,
          } as PersonalPreferenceChange);
        }}
        options={[
          {
            value: DEFAULT,
            // Not chosen: the value applied now is the default, so it is named.
            label: chosen.has(field)
              ? t('preferences.default')
              : t('preferences.default_value', { value: label(user[field]) }),
          },
          ...choices.map((value) => ({ value, label: label(value) })),
        ]}
      />
    </Space>
  );

  return (
    <Card title={t('preferences.title')} data-testid="preferences">
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Space direction="vertical" size={4}>
          <Typography.Text id="pref-theme-label">{t('appearance.theme')}</Typography.Text>
          <Segmented
            aria-labelledby="pref-theme-label"
            data-testid="pref-theme"
            value={user.theme_mode ?? 'system'}
            onChange={(value) => {
              setMode(value === 'system' ? systemMode() : value); // at once, here
              set({ field: 'theme_mode', value });
            }}
            options={THEMES.map((value) => ({ value, label: t(`appearance.theme.${value}`) }))}
          />
        </Space>
        <Space direction="vertical" size={4}>
          <Typography.Text id="pref-text-label">{t('preferences.text_scale')}</Typography.Text>
          <Select<number>
            aria-labelledby="pref-text-label"
            data-testid="pref-text-scale"
            style={{ width: 140 }}
            value={user.text_scale}
            onChange={(value) => {
              setTextScale(value);
              set({ field: 'text_scale', value });
            }}
            options={TEXT_SCALES.map((value) => ({ value, label: percent.format(value / 100) }))}
          />
        </Space>
        <Flex gap={16} wrap>
          {regional('week_start', WEEK_STARTS, (v) => t(`instance.week_start.${v}`))}
          {regional('date_format', DATE_FORMATS, (v) => v)}
          {regional('time_format', TIME_FORMATS, (v) => t(`instance.time_format.${v}`))}
          {regional('digits', DIGITS, (v) => t(`preferences.digits.${v}`))}
        </Flex>
      </Space>
    </Card>
  );
}
