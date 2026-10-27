import type { BrandingResult } from '@supportx/api-client';

import type { Branding } from '../theme';

/** Realtime notice from the organization module when a tenant's branding is saved. */
export const BRANDING_CHANGED = 'organization.branding_changed';

const orUndefined = (value: string | null | undefined) => value ?? undefined;

/**
 * The theme's brand from the API's (WP-017). The default brand (no tenant, or nothing chosen)
 * gives undefined, so the SupportX files and colours stay. Logos are replaced as a set: a tenant
 * that uploaded one keeps no SupportX variant beside it.
 */
// The public and signed-in reads type the gradient differently (tuple vs array) in the generated
// schema; only what both carry is read here.
type BrandSource = Omit<BrandingResult, 'gradient'> & { gradient: readonly string[] };

export function brandingFrom(result: BrandSource | undefined): Partial<Branding> | undefined {
  if (result?.tenant_slug == null || !result.customised) return undefined;
  const { logos } = result;
  const brand: Partial<Branding> = {
    colorPrimary: result.primary_colour,
    gradient: [
      result.gradient[0] ?? result.primary_colour,
      result.gradient[1] ?? result.primary_colour,
    ],
    texts: {
      productName: result.product_name,
      portalName: result.portal_name,
      welcomeText: result.welcome_text,
    },
    favicon: orUndefined(logos.favicon),
    appleTouchIcon: orUndefined(logos.apple_touch_icon),
  };
  if (logos.full != null) {
    brand.logos = {
      full: logos.full,
      fullOnDark: orUndefined(logos.full_on_dark),
      fullHighContrast: orUndefined(logos.full_high_contrast),
      icon: orUndefined(logos.icon),
      iconHighContrast: orUndefined(logos.icon_high_contrast),
    };
  }
  return brand;
}
