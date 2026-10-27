import {
  Button,
  Card,
  ConfigProvider,
  Flex,
  Input,
  Segmented,
  Typography,
  theme as antdTheme,
} from 'antd';
import { useMemo, useState } from 'react';

import {
  brandText,
  buildTheme,
  DEFAULT_BRANDING,
  logoFor,
  THEME_MODES,
  useAppearance,
  useLabel,
  type Branding,
  type ThemeMode,
} from '@supportx/ui';

type Surface = 'console' | 'portal' | 'sign_in';
const SURFACES: Surface[] = ['console', 'portal', 'sign_in'];

/** The page behind each theme, as the apps draw it (Ant Design's layout backgrounds). */
const PAGE_BACKGROUND: Record<ThemeMode, string> = {
  light: '#f5f5f5',
  dark: '#141414',
  high_contrast: '#ffffff',
};

function Logo({ brand, mode, height }: { brand: Branding; mode: ThemeMode; height: number }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const src = logoFor(brand.logos, mode, 'full');
  const name = brandText(brand, 'productName', locale) ?? t('product.name');
  return src === undefined ? (
    <Typography.Text strong>{name}</Typography.Text>
  ) : (
    <img src={src} alt={name} style={{ height, width: 'auto', maxWidth: '100%' }} />
  );
}

function Sample({ brand, mode, surface }: { brand: Branding; mode: ThemeMode; surface: Surface }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { token } = antdTheme.useToken();
  const band = `linear-gradient(90deg, ${brand.gradient[0]}, ${brand.gradient[1]})`;
  if (surface === 'console') {
    return (
      <Flex vertical gap={12}>
        <Flex
          align="center"
          justify="space-between"
          style={{
            padding: '8px 12px',
            background: token.colorBgContainer,
            borderBottom: `3px solid ${mode === 'high_contrast' ? '#000' : brand.gradient[1]}`,
          }}
        >
          <Logo brand={brand} mode={mode} height={24} />
          <Button type="primary" size="small">
            {t('branding.preview.new_incident')}
          </Button>
        </Flex>
        <Typography.Link>{t('branding.preview.link')}</Typography.Link>
      </Flex>
    );
  }
  if (surface === 'portal') {
    const welcome = brandText(brand, 'welcomeText', locale) ?? t('app.portal.name');
    const portal = brandText(brand, 'portalName', locale) ?? t('app.portal.name');
    return (
      <Flex vertical gap={8}>
        <Flex align="center" gap={8}>
          <Logo brand={brand} mode={mode} height={24} />
          <Typography.Text strong>{portal}</Typography.Text>
        </Flex>
        <div
          style={{
            background: mode === 'high_contrast' ? '#000' : band,
            color: '#fff',
            padding: '16px 12px',
            borderRadius: 8,
          }}
        >
          <Typography.Text style={{ color: '#fff' }}>{welcome}</Typography.Text>
        </div>
      </Flex>
    );
  }
  return (
    <Card
      size="small"
      style={{
        borderTop: `4px solid`,
        borderImage: `${mode === 'high_contrast' ? 'linear-gradient(#000, #000)' : band} 1`,
      }}
    >
      <Flex vertical gap={8} align="stretch">
        <Flex justify="center">
          <Logo brand={brand} mode={mode} height={32} />
        </Flex>
        <Input
          size="small"
          placeholder={t('branding.preview.email')}
          aria-label={t('branding.preview.email')}
        />
        <Button type="primary" size="small" block>
          {t('branding.preview.sign_in')}
        </Button>
      </Flex>
    </Card>
  );
}

/**
 * The brand being edited on each surface (console header, portal welcome band, sign-in card) in
 * light, dark and high contrast, drawn with the real theme builder before anything is saved.
 * Only a ConfigProvider per sample: the page's own theme and direction stay untouched.
 */
export function BrandPreview({ branding }: { branding: Partial<Branding> }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const [surface, setSurface] = useState<Surface>('console');
  const brand = useMemo<Branding>(() => ({ ...DEFAULT_BRANDING, ...branding }), [branding]);
  return (
    <Card title={t('branding.preview.title')} data-testid="branding-preview">
      <Flex vertical gap={12}>
        <Segmented
          value={surface}
          onChange={(value) => {
            setSurface(value);
          }}
          options={SURFACES.map((key) => ({ value: key, label: t(`branding.preview.${key}`) }))}
          data-testid="branding-preview-surface"
        />
        {THEME_MODES.map((mode) => (
          <section
            key={mode}
            aria-label={t(`appearance.theme.${mode}`)}
            data-testid={`branding-preview-${mode}`}
          >
            <Typography.Text type="secondary">{t(`appearance.theme.${mode}`)}</Typography.Text>
            <ConfigProvider theme={buildTheme(mode, brand, locale)}>
              <div style={{ background: PAGE_BACKGROUND[mode], padding: 12, borderRadius: 8 }}>
                <Sample brand={brand} mode={mode} surface={surface} />
              </div>
            </ConfigProvider>
          </section>
        ))}
      </Flex>
    </Card>
  );
}
