import type { AssetRecord, PickedAsset } from '@supportx/api-client';

export type RaiseKind = 'incident' | 'service_request' | 'change';

/** The create form's address with the asset and its holder filled in (REQ-AST-045). */
export function raisePath(kind: RaiseKind, template: string, asset: AssetRecord): string {
  const params = new URLSearchParams();
  params.set(kind === 'service_request' ? 'item' : 'template', template);
  if (kind !== 'change') params.set('asset', asset.id);
  if (asset.owner_user_id != null) params.set('requester', asset.owner_user_id);
  const base = {
    incident: '/incidents/new',
    service_request: '/requests/new',
    change: '/changes/new',
  };
  return `${base[kind]}?${params.toString()}`;
}

/** A prefilled asset as the form's picker names it (tag and name, never its ID). */
export function pickedOf(asset: AssetRecord): PickedAsset {
  return { id: asset.id, tag: asset.tag, name: asset.name, state_id: asset.state_id, mine: false };
}
