import type { ThemeMode } from '../theme';
import type { BrandLogos } from '.';

export type LogoVariant = 'full' | 'icon';

/** The logo file for a mode, falling back to the light one (a tenant may upload only that). */
export function logoFor(
  logos: BrandLogos,
  mode: ThemeMode,
  variant: LogoVariant,
): string | undefined {
  if (variant === 'icon') {
    return mode === 'high_contrast' ? (logos.iconHighContrast ?? logos.icon) : logos.icon;
  }
  if (mode === 'dark') return logos.fullOnDark ?? logos.full;
  if (mode === 'high_contrast') return logos.fullHighContrast ?? logos.full;
  return logos.full;
}
