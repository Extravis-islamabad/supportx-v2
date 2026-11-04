import type { CatalogItem } from '@supportx/api-client';

/** An item's name in the viewer's language, English as the fallback. */
export function itemName(item: Pick<CatalogItem, 'names'> | undefined, locale: string): string {
  if (item === undefined) return '';
  return item.names[locale] ?? item.names.en ?? '';
}
