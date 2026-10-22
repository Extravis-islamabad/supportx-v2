import { Select, Space, Switch, Typography } from 'antd';

import { LOCALES } from '@supportx/labels';

import { useAppearance, useLabel } from './appearance';

/** Dark-mode switch, RTL switch and language picker. */
export function AppearanceControls() {
  const { mode, direction, locale, setMode, setDirection, setLocale } = useAppearance();
  const t = useLabel();

  return (
    <Space size="large" wrap>
      <Space>
        <Typography.Text>{t('appearance.dark_mode')}</Typography.Text>
        <Switch
          aria-label={t('appearance.dark_mode')}
          checked={mode === 'dark'}
          onChange={(checked) => {
            setMode(checked ? 'dark' : 'light');
          }}
        />
      </Space>
      <Space>
        <Typography.Text>{t('appearance.right_to_left')}</Typography.Text>
        <Switch
          aria-label={t('appearance.right_to_left')}
          checked={direction === 'rtl'}
          onChange={(checked) => {
            setDirection(checked ? 'rtl' : 'ltr');
          }}
        />
      </Space>
      <Select
        aria-label={t('appearance.language')}
        value={locale}
        onChange={setLocale}
        options={LOCALES.map((value) => ({ value, label: t(`locale.${value}`) }))}
        style={{ minWidth: 120 }}
      />
    </Space>
  );
}
