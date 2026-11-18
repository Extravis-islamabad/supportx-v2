import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// WP-046b S2: parent and child incidents (REQ-INC-086, -092), merging with a preview and undo
// (REQ-INC-088, -150), and converting incidents and service requests (REQ-INC-089).

export type IncidentMergePreview = components['schemas']['IncidentMergePreviewOut'];
export type IncidentMerged = components['schemas']['IncidentMergeOut'];
export type ResolvableChild = components['schemas']['ResolvableChildOut'];
export type ConvertPreview = components['schemas']['ConvertPreviewOut'];
export type Converted = components['schemas']['ConvertedOut'];
export type RecordAlias = components['schemas']['AliasOut'];
/** Which list a convertible record lives in (its API path). */
export type ConvertibleKind = 'incidents' | 'service-requests';

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** Make another incident a child of this one, or remove a child link (edit on both). */
export function useChildChange(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: async (
      change:
        { kind: 'add'; childId: string } | { kind: 'remove'; linkId: string; version: number },
    ): Promise<void> => {
      if (change.kind === 'add') {
        await call(
          api.POST('/api/v1/incidents/{record_id}/children', {
            params: { path: { record_id: id } },
            body: { child_id: change.childId },
          }),
        );
        return;
      }
      await call(
        api.DELETE('/api/v1/incidents/{record_id}/children/{link_id}', {
          params: {
            path: { record_id: id, link_id: change.linkId },
            header: ifMatch(change.version),
          },
        }),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.links(id) });
    },
  });
}

/** The open children this person may resolve with the parent (REQ-INC-092). */
export function useResolvableChildren(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.incidents.links(id), 'resolvable'],
    queryFn: () =>
      call(
        api.GET('/api/v1/incidents/{record_id}/children/resolvable', {
          params: { path: { record_id: id } },
        }),
      ),
    enabled: enabled && id !== '',
  });
}

/** Resolve the chosen children with the parent's resolution: a bulk job (202). */
export function useResolveChildren(id: string) {
  return useMutation({
    meta: { silent: true },
    mutationFn: (childIds: string[]) =>
      call(
        api.POST('/api/v1/incidents/{record_id}/children/resolve', {
          params: { path: { record_id: id } },
          body: { child_ids: childIds },
        }),
      ),
  });
}

/** What merging this incident into another would do (counts and IDs only). */
export function useMergePreview(id: string, intoId: string | null) {
  return useQuery({
    queryKey: [...queryKeys.incidents.detail(id), 'merge-preview', intoId],
    queryFn: () =>
      call(
        api.GET('/api/v1/incidents/{record_id}/merge-preview', {
          params: { path: { record_id: id }, query: { into_id: intoId ?? '' } },
        }),
      ),
    enabled: id !== '' && intoId !== null,
    staleTime: 0,
  });
}

/** Merge into another incident (If-Match), confirming a wider audience when asked. */
export function useMergeIncident(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      intoId,
      confirm,
      version,
    }: {
      intoId: string;
      confirm: boolean;
      version: number;
    }) =>
      call(
        api.POST('/api/v1/incidents/{record_id}/merge', {
          params: { path: { record_id: id }, header: ifMatch(version) },
          body: { into_id: intoId, confirm_wider_audience: confirm },
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.all });
    },
  });
}

/** Undo a merge (If-Match; needs the right and may ask to confirm the sign-in). */
export function useUndoMerge(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (version: number) =>
      call(
        api.POST('/api/v1/incidents/{record_id}/undo-merge', {
          params: { path: { record_id: id }, header: ifMatch(version) },
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.all });
    },
  });
}

/** What converting would carry and leave behind (field keys only). */
export function useConvertPreview(kind: ConvertibleKind, id: string, enabled: boolean) {
  return useQuery({
    queryKey: [kind, 'detail', id, 'convert-preview'],
    queryFn: () =>
      kind === 'incidents'
        ? call(
            api.GET('/api/v1/incidents/{record_id}/convert-preview', {
              params: { path: { record_id: id } },
            }),
          )
        : call(
            api.GET('/api/v1/service-requests/{record_id}/convert-preview', {
              params: { path: { record_id: id } },
            }),
          ),
    enabled: enabled && id !== '',
    staleTime: 0,
  });
}

/** The other type's inputs: a request's catalog item and answers, an incident's template. */
export interface ConvertInput {
  catalogItemId?: string;
  answers?: Record<string, unknown>;
  templateId?: string;
  version: number;
}

/** Convert to the other type (If-Match): the old record becomes `converted`. */
export function useConvertRecord(kind: ConvertibleKind, id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ catalogItemId, answers, templateId, version }: ConvertInput) => {
      const body = {
        catalog_item_id: catalogItemId ?? null,
        answers: answers ?? null,
        template_id: templateId ?? null,
      };
      return kind === 'incidents'
        ? call(
            api.POST('/api/v1/incidents/{record_id}/convert', {
              params: { path: { record_id: id }, header: ifMatch(version) },
              body,
            }),
          )
        : call(
            api.POST('/api/v1/service-requests/{record_id}/convert', {
              params: { path: { record_id: id }, header: ifMatch(version) },
              body,
            }),
          );
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: [kind] });
    },
  });
}

/** Where an old (converted) number leads now; 404 unless the reader may read that record. */
export async function followAlias(kind: ConvertibleKind, value: string): Promise<RecordAlias> {
  return kind === 'incidents'
    ? call(api.GET('/api/v1/incidents/alias/{value}', { params: { path: { value } } }))
    : call(api.GET('/api/v1/service-requests/alias/{value}', { params: { path: { value } } }));
}

/** A record's links by its kind: the banner finds where a merged or converted record went. */
export function useMovedLinks(kind: ConvertibleKind, id: string, enabled: boolean) {
  return useQuery({
    queryKey:
      kind === 'incidents'
        ? queryKeys.incidents.links(id)
        : ['service-requests', 'detail', id, 'links'],
    queryFn: () =>
      kind === 'incidents'
        ? call(
            api.GET('/api/v1/incidents/{record_id}/links', {
              params: { path: { record_id: id } },
            }),
          )
        : call(
            api.GET('/api/v1/service-requests/{record_id}/links', {
              params: { path: { record_id: id } },
            }),
          ),
    enabled: enabled && id !== '',
  });
}

/** Where a typed old number leads now; nothing (no error) when it leads nowhere you may read. */
export function useAliasLookup(value: string, enabled: boolean) {
  const wanted = value.trim().toUpperCase();
  return useQuery({
    queryKey: ['alias', wanted],
    queryFn: async () => {
      try {
        return await followAlias('incidents', wanted);
      } catch {
        return null; // 404 for an unknown or unreadable number: offer nothing, say nothing
      }
    },
    enabled: enabled && /^[A-Z]{2,10}-\d{1,12}$/.test(wanted),
    staleTime: 30_000,
  });
}
