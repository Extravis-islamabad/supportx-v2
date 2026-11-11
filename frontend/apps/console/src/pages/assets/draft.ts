import type { AssetRecord } from '@supportx/api-client';

/** The fields a person sets on an asset (state moves through the life cycle, not here). */
export interface AssetDraft {
  name: string;
  product_id: string;
  tag: string;
  serial_number: string;
  barcode: string;
  vendor_id: string | null;
  location: string;
  /** REQ-AST-038: free text until real cost centres arrive (WP-054). */
  cost_centre: string;
  gl_code: string;
  purchase_price: string | null;
  purchase_tax: string | null;
  currency: string;
  acquired_on: string | null;
  warranty_expires_on: string | null;
  description: string;
  /** Custom values by field key (REQ-AST-007; metadata checks them). */
  custom: Record<string, unknown>;
}

export function draftOf(asset: AssetRecord | null): AssetDraft {
  return {
    name: asset?.name ?? '',
    product_id: asset?.product_id ?? '',
    tag: asset?.tag ?? '',
    serial_number: asset?.serial_number ?? '',
    barcode: asset?.barcode ?? '',
    vendor_id: asset?.vendor_id ?? null,
    location: asset?.location ?? '',
    cost_centre: asset?.cost_centre ?? '',
    gl_code: asset?.gl_code ?? '',
    purchase_price: asset?.purchase_price ?? null,
    purchase_tax: asset?.purchase_tax ?? null,
    currency: asset?.currency ?? '',
    acquired_on: asset?.acquired_on ?? null,
    warranty_expires_on: asset?.warranty_expires_on ?? null,
    description: asset?.description ?? '',
    custom: { ...(asset?.custom ?? {}) },
  };
}

/** What a save sends: blanks as null; for a change, only what differs from `before`. */
export function bodyOf(draft: AssetDraft, before?: AssetDraft): Record<string, unknown> {
  const blank = (value: string) => (value.trim() === '' ? null : value.trim());
  const body: Record<string, unknown> = {
    name: draft.name.trim(),
    product_id: draft.product_id,
    tag: blank(draft.tag),
    serial_number: blank(draft.serial_number),
    barcode: blank(draft.barcode),
    vendor_id: draft.vendor_id,
    location: blank(draft.location),
    cost_centre: blank(draft.cost_centre),
    gl_code: blank(draft.gl_code),
    purchase_price: draft.purchase_price,
    purchase_tax: draft.purchase_tax,
    currency: blank(draft.currency.toUpperCase()),
    acquired_on: draft.acquired_on,
    warranty_expires_on: draft.warranty_expires_on,
    description: blank(draft.description),
  };
  if (before === undefined) {
    const set = Object.fromEntries(Object.entries(draft.custom).filter(([, v]) => v != null));
    const created = Object.fromEntries(Object.entries(body).filter(([, v]) => v !== null));
    return Object.keys(set).length === 0 ? created : { ...created, custom: set };
  }
  const old = bodyOf(before);
  const changed = Object.fromEntries(
    Object.entries(body).filter(([k, v]) => k !== 'custom' && v !== (old[k] ?? null)),
  );
  // Only the custom values that changed; null clears one (the API's PATCH semantics).
  const keys = new Set([...Object.keys(draft.custom), ...Object.keys(before.custom)]);
  const custom: Record<string, unknown> = {};
  for (const key of keys) {
    const now = draft.custom[key] ?? null;
    if (JSON.stringify(now) !== JSON.stringify(before.custom[key] ?? null)) custom[key] = now;
  }
  return Object.keys(custom).length === 0 ? changed : { ...changed, custom };
}
