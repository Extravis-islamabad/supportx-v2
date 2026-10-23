import { Segmented, Select, Space, Switch, Typography } from 'antd';

import { LOCALES } from '@supportx/labels';

import { useAppearance, useLabel } from './appearance';
import { THEME_MODES } from './theme';

/** Theme mode, RTL switch and language picker. */
export function AppearanceControls() {
  const { mode, direction, locale, setMode, setDirection, setLocale } = useAppearance();
  const t = useLabel();

  return (
    <Space size="large" wrap>
      <Space>
        <Typography.Text id="appearance-theme-label">{t('appearance.theme')}</Typography.Text>
        <Segmented
          aria-labelledby="appearance-theme-label"
          value={mode}
          onChange={setMode}
          options={THEME_MODES.map((value) => ({ value, label: t(`appearance.theme.${value}`) }))}
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
        data-testid="language-select"
        value={locale}
        onChange={setLocale}
        options={LOCALES.map((value) => ({ value, label: t(`locale.${value}`) }))}
        style={{ minWidth: 120 }}
      />
    </Space>
  );
}
