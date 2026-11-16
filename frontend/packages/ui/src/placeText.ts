import { useCallback } from 'react';

import { useStructure, type components } from '@supportx/api-client';

import { useAppearance, useLabel } from './appearance';

export type Place = components['schemas']['PlaceOut'];

/** A country's name in the reader's language, from its ISO code (the code itself if unknown). */
function countryName(locale: string, code: string): string {
  try {
    return new Intl.DisplayNames([locale], { type: 'region' }).of(code) ?? code;
  } catch {
    return code;
  }
}

/**
 * A sign-in's approximate place in words (WP-057 S2b, D-170): the mapped site's name, "Internal
 * network", or "City, Country" with the country in the reader's language. Null when there is
 * none. A site the reader may not list (or since deleted) reads "A mapped site".
 */
export function usePlaceText(): (place: Place | null | undefined) => string | null {
  const t = useLabel();
  const { locale } = useAppearance();
  // Silent: a person reading their own sessions may not list sites; the place still says "site".
  const sites = useStructure('sites', true, true);
  return useCallback(
    (place: Place | null | undefined) => {
      if (place == null) return null;
      if (place.kind === 'internal') return t('sign_in_place.internal');
      if (place.kind === 'site') {
        const site = sites.data?.find((s) => s.id === place.site_id);
        return site?.name ?? t('sign_in_place.site_unknown');
      }
      const country = place.country == null ? null : countryName(locale, place.country);
      if (place.city != null && country != null) {
        return t('sign_in_place.city_country', { city: place.city, country });
      }
      return place.city ?? country;
    },
    [t, locale, sites.data],
  );
}
