import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// CMDB sync rules from assets and which source wins (WP-053 S4a; REQ-CMDB-015, 016).
export type SyncRule = components['schemas']['SyncRuleOut'];
export type SyncRuleInput = components['schemas']['SyncRuleIn'];
export type SyncFields = components['schemas']['SyncFieldsOut'];
export type SyncPreview = components['schemas']['SyncPreviewOut'];
export type SyncRun = components['schemas']['SyncRunOut'];
export type SyncRunDetail = components['schemas']['SyncRunDetailOut'];
export type SyncRunItem = components['schemas']['SyncRunItemOut'];
export type SourcePrecedence = components['schemas']['SourcePrecedenceOut'];
export type AttributeSourceCode = components['schemas']['AttributeSource'];
export type AttributeStamp = components['schemas']['AttributeStampOut'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

function useSyncSaved() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.sync.all });
  };
}

export function useSyncRules(enabled = true) {
  return useQuery({
    queryKey: queryKeys.cmdb.sync.rules,
    queryFn: () => call(api.GET('/api/v1/cmdb/sync-rules')),
    enabled,
  });
}

export function useSyncRule(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.cmdb.sync.rule(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/cmdb/sync-rules/{rule_id}', { params: { path: { rule_id: id ?? '' } } }),
      ),
    enabled: id !== undefined,
  });
}

/** What a rule may map; `typeId` adds that CI type's custom text fields. */
export function useSyncFields(typeId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.cmdb.sync.fields(typeId ?? null),
    queryFn: () =>
      call(api.GET('/api/v1/cmdb/sync-rules/fields', { params: { query: { type_id: typeId } } })),
    enabled,
  });
}

/** What an unsaved rule would do now; nothing is written. */
export function usePreviewSyncRule() {
  return useMutation({
    meta: { silent: true },
    mutationFn: (body: SyncRuleInput) =>
      call(api.POST('/api/v1/cmdb/sync-rules/preview', { body })),
  });
}

export function useCreateSyncRule() {
  const saved = useSyncSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: SyncRuleInput; key: string }) =>
      call(
        api.POST('/api/v1/cmdb/sync-rules', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSuccess: saved,
  });
}

export function useUpdateSyncRule() {
  const saved = useSyncSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, body, version }: { id: string; body: SyncRuleInput; version: number }) =>
      call(
        api.PUT('/api/v1/cmdb/sync-rules/{rule_id}', {
          params: { path: { rule_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    onSuccess: saved,
  });
}

export function useDeleteSyncRule() {
  const saved = useSyncSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/cmdb/sync-rules/{rule_id}', {
          params: { path: { rule_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: saved,
  });
}

export function useSyncRuns(ruleId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.cmdb.sync.runs(ruleId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/cmdb/sync-rules/{rule_id}/runs', {
          params: { path: { rule_id: ruleId ?? '' } },
        }),
      ),
    enabled: ruleId !== undefined,
  });
}

export function useSyncRun(runId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.cmdb.sync.run(runId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/cmdb/sync-runs/{run_id}', { params: { path: { run_id: runId ?? '' } } }),
      ),
    enabled: runId !== undefined,
  });
}

export function useStartSyncRun() {
  const saved = useSyncSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ ruleId, key }: { ruleId: string; key: string }) =>
      call(
        api.POST('/api/v1/cmdb/sync-rules/{rule_id}/runs', {
          params: { path: { rule_id: ruleId }, header: { 'Idempotency-Key': key } },
        }),
      ),
    onSuccess: saved,
  });
}

export function useSourcePrecedence(enabled = true) {
  return useQuery({
    queryKey: queryKeys.cmdb.sync.precedence,
    queryFn: () => call(api.GET('/api/v1/cmdb/settings/source-precedence')),
    enabled,
  });
}

export function useUpdateSourcePrecedence() {
  const saved = useSyncSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      order,
      overrides,
      version,
    }: {
      order: AttributeSourceCode[];
      overrides: Record<string, AttributeSourceCode[]>;
      version: number;
    }) =>
      call(
        api.PUT('/api/v1/cmdb/settings/source-precedence', {
          params: { header: ifMatch(version) },
          body: { order, overrides },
        }),
      ),
    onSuccess: saved,
  });
}
