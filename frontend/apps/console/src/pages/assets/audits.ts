import { useQueryClient } from '@tanstack/react-query';

import {
  queryKeys,
  type AssetAudit,
  type AssetAuditInput,
  type AssetAuditKind,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';

// Shared by the audit list and the audit record (WP-049b s3): live refresh, state tones, and the
// plan form's draft.

export const AUDITS_CHANGED = 'assets.audits_changed';
export const AUDIT_STATE_TONES = { draft: 'default', running: 'info', closed: 'success' } as const;

/** Refetch the audits when one changed (rule c; IDs only). */
export function useAuditsLive() {
  const queryClient = useQueryClient();
  useTenantChannel((event) => {
    if (event.type !== AUDITS_CHANGED) return;
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.audits });
  });
}

export interface AuditDraft {
  name: string;
  kind: AssetAuditKind;
  description: string;
  site_ids: string[];
  product_type_ids: string[];
  group_ids: string[];
  planned_start: string | null;
  planned_end: string | null;
  auditor_ids: string[];
}

export function draftOfAudit(audit?: AssetAudit): AuditDraft {
  return {
    name: audit?.name ?? '',
    kind: audit?.kind ?? 'technician',
    description: audit?.description ?? '',
    site_ids: audit?.site_ids ?? [],
    product_type_ids: audit?.product_type_ids ?? [],
    group_ids: audit?.group_ids ?? [],
    planned_start: audit?.planned_start ?? null,
    planned_end: audit?.planned_end ?? null,
    auditor_ids: audit?.auditors.map((a) => a.id) ?? [],
  };
}

export function bodyOfAudit(draft: AuditDraft): AssetAuditInput {
  return {
    name: draft.name.trim(),
    kind: draft.kind,
    description: draft.description.trim() === '' ? null : draft.description,
    site_ids: draft.site_ids,
    product_type_ids: draft.product_type_ids,
    group_ids: draft.group_ids,
    planned_start: draft.planned_start,
    planned_end: draft.planned_end,
    auditor_ids: draft.auditor_ids,
  };
}
