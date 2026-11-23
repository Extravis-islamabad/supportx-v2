import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// Asset audits, labels, scan history and the overdue-scan rule (WP-049b s3; REQ-AST-039, 042,
// 043, 054, 056). Every change arrives live: an audit's own channel (`assets.audit_changed`,
// progress and items), the tenant channel for the audit lists, the person's channel for their
// label jobs, and the asset's channel (`fields`: scans) for its Scans tab.

type S = components['schemas'];
export type AssetAudit = S['AuditOut'];
export type AssetAuditInput = S['AuditIn'];
export type AssetAuditPatch = S['AuditPatch'];
export type AssetAuditItem = S['AuditItemOut'];
export type AssetAuditKind = S['AuditKind'];
export type AssetAuditState = S['AuditState'];
export type AssetAuditResult = S['AuditItemResult'];
export type AssetAuditFix = S['AuditFix'];
export type AssetAuditFixInput = S['AuditFixIn'];
export type AssetAuditFixes = S['AuditFixesOut'];
export type AssetLabelsInput = S['LabelsIn'];
export type AssetLabelJob = S['LabelJobOut'];
export type AssetLabelPrint = S['LabelPrintOut'];
export type AssetLabelLayout = S['LabelLayout'];
export type AssetLabelSymbology = S['Symbology'];
export type AssetScan = S['AssetScanOut'];
export type AssetScanChange = S['ScanChangeOut'];
export type AssetOverdueRule = S['OverdueRuleOut'];
export type AssetOverdueRuleInput = S['OverdueRuleIn'];
export type AssetOverdueRun = S['OverdueRunOut'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });
const idempotent = (key: string) => ({ 'Idempotency-Key': key });

// --- audits ---------------------------------------------------------------------------------

/** The audits you may open (all with assets.manage, else those you audit). */
export function useAssetAudits() {
  return useQuery({
    queryKey: queryKeys.assets.audits,
    queryFn: () => call(api.GET('/api/v1/assets/audits')),
  });
}

/** One audit with its auditors and progress. */
export function useAssetAudit(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.assets.audit(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/audits/{audit_id}', { params: { path: { audit_id: id ?? '' } } }),
      ),
    enabled: id !== undefined,
  });
}

/** The audit's items, or only its discrepancies. */
export function useAssetAuditItems(id: string | undefined, discrepancies = false) {
  return useQuery({
    queryKey: queryKeys.assets.auditItems(id ?? '', discrepancies),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/audits/{audit_id}/items', {
          params: { path: { audit_id: id ?? '' }, query: { discrepancies } },
        }),
      ),
    enabled: id !== undefined,
  });
}

/** Plan, change, start and close audits; the audit and the lists refetch after. */
export function useAssetAuditActions() {
  const queryClient = useQueryClient();
  const refresh = (id?: string) => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.audits });
    if (id !== undefined) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.audit(id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.auditItemsAll(id) });
    }
  };
  const create = useMutation({
    meta: { silent: true },
    mutationFn: (input: { body: AssetAuditInput; key: string }) =>
      call(
        api.POST('/api/v1/assets/audits', {
          params: { header: idempotent(input.key) },
          body: input.body,
        }),
      ),
    onSettled: () => {
      refresh();
    },
  });
  const update = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; version: number; body: AssetAuditPatch }) =>
      call(
        api.PATCH('/api/v1/assets/audits/{audit_id}', {
          params: { header: ifMatch(input.version), path: { audit_id: input.id } },
          body: input.body,
        }),
      ),
    onSettled: (_data, _error, input) => {
      refresh(input.id);
    },
  });
  const start = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; version: number }) =>
      call(
        api.POST('/api/v1/assets/audits/{audit_id}/start', {
          params: { header: ifMatch(input.version), path: { audit_id: input.id } },
        }),
      ),
    onSettled: (_data, _error, input) => {
      refresh(input.id);
    },
  });
  const close = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; version: number }) =>
      call(
        api.POST('/api/v1/assets/audits/{audit_id}/close', {
          params: { header: ifMatch(input.version), path: { audit_id: input.id } },
        }),
      ),
    onSettled: (_data, _error, input) => {
      refresh(input.id);
    },
  });
  return { create, update, start, close };
}

/** Mark items (named auditors), scan codes, and settle discrepancies (assets.manage). */
export function useAssetAuditWork(auditId: string) {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.audit(auditId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.auditItemsAll(auditId) });
  };
  const mark = useMutation({
    meta: { silent: true },
    mutationFn: (input: {
      id: string;
      version: number;
      result: AssetAuditResult;
      seenSiteId?: string | null;
      note?: string | null;
    }) =>
      call(
        api.PATCH('/api/v1/assets/audits/{audit_id}/items/{item_id}', {
          params: {
            header: ifMatch(input.version),
            path: { audit_id: auditId, item_id: input.id },
          },
          body: {
            result: input.result,
            seen_site_id: input.seenSiteId ?? null,
            note: input.note ?? null,
          },
        }),
      ),
    onSettled: refresh,
  });
  const scan = useMutation({
    meta: { silent: true },
    mutationFn: (input: { code: string; seenSiteId?: string | null; key: string }) =>
      call(
        api.POST('/api/v1/assets/audits/{audit_id}/scans', {
          params: { header: idempotent(input.key), path: { audit_id: auditId } },
          body: { code: input.code, seen_site_id: input.seenSiteId ?? null, result: 'found' },
        }),
      ),
    onSettled: refresh,
  });
  const fix = useMutation({
    meta: { silent: true },
    mutationFn: (input: { body: AssetAuditFixInput; key: string }) =>
      call(
        api.POST('/api/v1/assets/audits/{audit_id}/fixes', {
          params: { header: idempotent(input.key), path: { audit_id: auditId } },
          body: input.body,
        }),
      ),
    onSettled: () => {
      refresh();
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.all });
    },
  });
  return { mark, scan, fix };
}

// --- labels ---------------------------------------------------------------------------------

/** Your label jobs, newest first (live on your channel). */
export function useAssetLabelJobs(enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.labelJobs,
    queryFn: () => call(api.GET('/api/v1/assets/labels/jobs')),
    enabled,
  });
}

/** The label history: every print and reprint (for one asset when given). */
export function useAssetLabelPrints(assetId?: string) {
  return useQuery({
    queryKey: queryKeys.assets.labelPrints(assetId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/labels/prints', {
          params: { query: { asset_id: assetId } },
        }),
      ),
  });
}

/** Ask for labels (a job in the background) and reprint earlier ones. */
export function useAssetLabelActions() {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.labelJobs });
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.labelPrintsAll });
  };
  const print = useMutation({
    meta: { silent: true },
    mutationFn: (input: { body: AssetLabelsInput; key: string }) =>
      call(
        api.POST('/api/v1/assets/labels', {
          params: { header: idempotent(input.key) },
          body: input.body,
        }),
      ),
    onSettled: refresh,
  });
  const reprint = useMutation({
    meta: { silent: true },
    mutationFn: (input: { printId: string; key: string }) =>
      call(
        api.POST('/api/v1/assets/labels/prints/{print_id}/reprint', {
          params: { header: idempotent(input.key), path: { print_id: input.printId } },
        }),
      ),
    onSettled: refresh,
  });
  return { print, reprint };
}

/** Where a ready label PDF downloads from (the browser sends the session cookie). */
export function labelFileUrl(jobId: string): string {
  return `/api/v1/assets/labels/jobs/${encodeURIComponent(jobId)}/file`;
}

// --- scans and the overdue-scan rule --------------------------------------------------------

/** An asset's scans, newest first (the first 100). */
export function useAssetScans(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.assets.scans(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/{asset_id}/scans', {
          params: { path: { asset_id: id ?? '' }, query: { limit: 100 } },
        }),
      ),
    enabled: id !== undefined,
  });
}

/** The overdue-scan rule (config.assets). */
export function useAssetOverdueRule(enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.overdueRule,
    queryFn: () => call(api.GET('/api/v1/assets/overdue-rule')),
    enabled,
  });
}

/** The rule's latest runs, each with what it changed. */
export function useAssetOverdueRuns(enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.overdueRuns,
    queryFn: () => call(api.GET('/api/v1/assets/overdue-rule/runs')),
    enabled,
  });
}

/** The states the rule may move these product types' assets to (their life cycles reach). */
export function useAssetOverdueStates(productTypeIds: string[], enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.overdueStates(productTypeIds),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/overdue-rule/states', {
          params: { query: { product_type_ids: productTypeIds } },
        }),
      ),
    enabled,
  });
}

/** Preview and save the rule (If-Match). */
export function useAssetOverdueRuleActions() {
  const queryClient = useQueryClient();
  const preview = useMutation({
    meta: { silent: true },
    mutationFn: (body: AssetOverdueRuleInput) =>
      call(api.POST('/api/v1/assets/overdue-rule/preview', { body })),
  });
  const save = useMutation({
    meta: { silent: true },
    mutationFn: (input: { version: number; body: AssetOverdueRuleInput }) =>
      call(
        api.PATCH('/api/v1/assets/overdue-rule', {
          params: { header: ifMatch(input.version) },
          body: input.body,
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.overdueRule });
    },
  });
  return { preview, save };
}
