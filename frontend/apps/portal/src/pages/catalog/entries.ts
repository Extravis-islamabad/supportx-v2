import type { CatalogItem } from '@supportx/api-client';

/** Where an entry leads: its request form, or the incident form for a "report a problem" entry. */
export function entryPath(item: CatalogItem): string {
  return item.kind === 'incident_template' && item.template_id !== null
    ? `/requests/new?template=${item.template_id}`
    : `/catalog/items/${item.id}`;
}
