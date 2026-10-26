import icon from './assets/icon.png';
import iconHighContrast from './assets/icon-high-contrast.png';
import logoDarkText from './assets/logo-dark-text.png';
import logoHighContrast from './assets/logo-high-contrast.png';
import logoWhiteText from './assets/logo-white-text.png';
import palette from './palette.json';

/**
 * The SupportX brand, from one place (docs/architecture/branding.md): the colours in
 * `palette.json` (also read by `make brand-assets` for the favicons' manifest and the Keycloak
 * login theme) and the logos generated from docs/brand/supportx-logo-dark-text.png.
 * WP-017 replaces these per tenant through `Branding` (theme.ts); nothing else imports the files.
 */
export interface BrandLogos {
  /** Full logo for light backgrounds (dark text). */
  full: string;
  /** Full logo for dark backgrounds; `full` when absent. */
  fullOnDark?: string;
  /** One-colour full logo for high contrast; `full` when absent. */
  fullHighContrast?: string;
  /** Square mark for narrow places (compact sidebar); the short name when absent. */
  icon?: string;
  /** One-colour mark for high contrast; `icon` when absent. */
  iconHighContrast?: string;
}

export const SUPPORTX_LOGOS: BrandLogos = {
  full: logoDarkText,
  fullOnDark: logoWhiteText,
  fullHighContrast: logoHighContrast,
  icon,
  iconHighContrast,
};

/** Primary seed (gradient midpoint, AA with white text) and the decorative gradient. */
export const SUPPORTX_COLOURS = {
  primary: palette.primary,
  gradient: [palette.gradient.start, palette.gradient.end] as const,
};

export { BrandLogo, type BrandLogoProps } from './BrandLogo';
export { logoFor, type LogoVariant } from './logos';
export { BrandedPage } from './BrandedPage';
