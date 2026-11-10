import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// An asset's money and notes (WP-049b s2; REQ-AST-036..038, 050). Amounts are exact decimals:
// strings from the API, never floats. The asset's channel says which part changed (`fields`:
// "costs" or "notes"); the page refetches that part. Money needs `assets.view_financials`: the
// screen asks only when the person holds it, and the server refuses otherwise.

type S = components['schemas'];
export type AssetFinancials = S['AssetFinancialsOut'];
export type AssetCost = S['AssetCostOut'];
export type AssetCostInput = S['AssetCostIn'];
export type AssetCostPatch = S['AssetCostPatch'];
export type AssetCostKind = S['CostKind'];
export type AssetDepreciationChoice = S['DepreciationChoice'];
export type AssetTermsSource = S['TermsSource'];
export type AssetDepreciationYear = S['DepreciationYearOut'];
export type AssetNote = S['AssetNoteOut'];
export type AssetNoteSaved = S['AssetNoteSavedOut'];
export type AssetNoteVersion = S['AssetNoteVersionOut'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });
const idempotent = (key: string) => ({ 'Idempotency-Key': key });

/** The Financials tab: totals, depreciation in effect, book value and the cost lines. */
export function useAssetFinancials(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.financials(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/{asset_id}/financials', {
          params: { path: { asset_id: id ?? '' } },
        }),
      ),
    enabled: enabled && id !== undefined,
  });
}

/** Add, change and remove an asset's cost lines; its money and history refetch after. */
export function useAssetCostActions(assetId: string) {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.financials(assetId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.history(assetId) });
  };
  const create = useMutation({
    meta: { silent: true },
    mutationFn: (input: { body: AssetCostInput; key: string }) =>
      call(
        api.POST('/api/v1/assets/{asset_id}/costs', {
          params: { header: idempotent(input.key), path: { asset_id: assetId } },
          body: input.body,
        }),
      ),
    onSettled: refresh,
  });
  const update = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; version: number; body: AssetCostPatch }) =>
      call(
        api.PATCH('/api/v1/assets/{asset_id}/costs/{cost_id}', {
          params: {
            header: ifMatch(input.version),
            path: { asset_id: assetId, cost_id: input.id },
          },
          body: input.body,
        }),
      ),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: async (input: { id: string; version: number }) => {
      await call(
        api.DELETE('/api/v1/assets/{asset_id}/costs/{cost_id}', {
          params: {
            header: ifMatch(input.version),
            path: { asset_id: assetId, cost_id: input.id },
          },
        }),
      );
    },
    onSettled: refresh,
  });
  return { create, update, remove };
}

/** The asset's notes, newest first (deleted ones as "note deleted" lines). */
export function useAssetNotes(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.assets.notes(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/{asset_id}/notes', { params: { path: { asset_id: id ?? '' } } }),
      ),
    enabled: id !== undefined,
  });
}

/** A note's earlier texts, newest first (behind its "edited" marker). */
export function useAssetNoteHistory(assetId: string, noteId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.assets.noteHistory(noteId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/{asset_id}/notes/{note_id}/history', {
          params: { path: { asset_id: assetId, note_id: noteId ?? '' } },
        }),
      ),
    enabled: noteId !== undefined,
  });
}

/** Add, edit and delete notes on an asset; its notes and history refetch after. */
export function useAssetNoteActions(assetId: string) {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.notes(assetId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.history(assetId) });
  };
  const create = useMutation({
    meta: { silent: true },
    mutationFn: (input: { body: string; key: string }) =>
      call(
        api.POST('/api/v1/assets/{asset_id}/notes', {
          params: { header: idempotent(input.key), path: { asset_id: assetId } },
          body: { body: input.body },
        }),
      ),
    onSettled: refresh,
  });
  const edit = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; version: number; body: string }) =>
      call(
        api.PATCH('/api/v1/assets/{asset_id}/notes/{note_id}', {
          params: {
            header: ifMatch(input.version),
            path: { asset_id: assetId, note_id: input.id },
          },
          body: { body: input.body },
        }),
      ),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: async (input: { id: string; version: number }) => {
      await call(
        api.DELETE('/api/v1/assets/{asset_id}/notes/{note_id}', {
          params: {
            header: ifMatch(input.version),
            path: { asset_id: assetId, note_id: input.id },
          },
        }),
      );
    },
    onSettled: refresh,
  });
  return { create, edit, remove };
}

/** People to @mention in a note: staff found by name or email (the server tells who was not
 * told because they cannot see the asset, REQ-INC-063 AC2). */
export async function findMentionable(query: string) {
  const page = await call(
    api.GET('/api/v1/users', {
      params: {
        query: {
          q: query.trim() === '' ? undefined : query.trim(),
          filter: JSON.stringify({ field: 'user_type', op: 'eq', value: 'technician' }),
          limit: 10,
        },
      },
    }),
  );
  return page.items;
}
