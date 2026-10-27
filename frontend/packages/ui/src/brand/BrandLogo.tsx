import { Typography } from 'antd';

import { useAppearance, useLabel } from '../appearance';
import { brandText } from './texts';
import { logoFor, type LogoVariant } from './logos';

export interface BrandLogoProps {
  variant?: LogoVariant;
  /** Rendered height in CSS pixels (the files are drawn at three times the usual sizes). */
  height?: number;
}

/**
 * The product's (or, with WP-017, the tenant's) logo in the version that suits the current
 * theme: dark text on light, white text on dark, one colour in high contrast. Its accessible
 * name is the product name. Without an icon file the narrow variant shows the short name.
 */
export function BrandLogo({ variant = 'full', height = 32 }: BrandLogoProps) {
  const t = useLabel();
  const { mode, branding, locale } = useAppearance();
  const src = logoFor(branding.logos, mode, variant);
  const name = brandText(branding, 'productName', locale);
  if (src === undefined) {
    return (
      <Typography.Text strong style={{ fontSize: 18, whiteSpace: 'nowrap' }}>
        {name ?? t('product.short_name')}
      </Typography.Text>
    );
  }
  return (
    <img
      src={src}
      alt={name ?? t('product.name')}
      data-testid={`brand-logo-${variant}`}
      style={{ display: 'block', height, width: 'auto', maxWidth: '100%' }}
    />
  );
}
