import { Segmented, Select, Space, Switch, Typography } from 'antd';

import type { NavLayout } from '@supportx/api-client';
import { LOCALES } from '@supportx/labels';

import { useAppearance, useLabel } from './appearance';
import { NAV_LAYOUTS } from './shell/nav';
import { THEME_MODES } from './theme';

export interface AppearanceControlsProps {
  /** The user's navigation layout; with `onNavLayoutChange` the choice is offered (console). */
  navLayout?: NavLayout;
  onNavLayoutChange?: (layout: NavLayout) => void;
}

/** Theme mode, navigation layout, RTL switch and language picker. */
export function AppearanceControls({ navLayout, onNavLayoutChange }: AppearanceControlsProps) {
  const { mode, direction, locale, setMode, setDirection, setLocale } = useAppearance();
  const t = useLabel();

  return (
    <Space size="large" wrap>
      {navLayout !== undefined && onNavLayoutChange !== undefined && (
        <Space>
          <Typography.Text id="appearance-navigation-label">
            {t('appearance.navigation')}
          </Typography.Text>
          <Segmented
            aria-labelledby="appearance-navigation-label"
            data-testid="nav-layout"
            value={navLayout}
            onChange={onNavLayoutChange}
            options={NAV_LAYOUTS.map((value) => ({ value, label: t(`nav_layout.${value}`) }))}
          />
        </Space>
      )}
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
