import { type QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import type { IncidentsQuery } from './incidents';
import { queryKeys } from './keys';
import type { components } from './schema';

// Saved views, list settings and bulk jobs of the incident list (WP-020d; REQ-INC-104, 106, 110,
// 119, 120).

export type IncidentListField = components['schemas']['ListFieldOut'];
export type IncidentViewFilter = components['schemas']['ViewFilterOut'];
export type SavedView = components['schemas']['SavedViewOut'];
export type SavedViewInput = components['schemas']['SavedViewIn'];
export type ListColumn = components['schemas']['ListColumn'];
export type ListSetting = components['schemas']['ListSettingOut'];
export type ListSettingInput = components['schemas']['ListSettingIn'];
export type BulkAction = components['schemas']['BulkAction'];
export type BulkJob = components['schemas']['BulkJobOut'];
export type BulkResult = components['schemas']['BulkResultOut'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** Every field the list filters, sorts or shows, with the tenant's custom fields. */
export function useIncidentListFields(enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.listFields,
    queryFn: () => call(api.GET('/api/v1/incidents/list-fields')),
    enabled,
    staleTime: 60_000,
  });
}

/** Each built-in view as a filter (for the export, which takes a filter and not a view). */
export function useIncidentViewFilters(enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.viewFilters,
    queryFn: () => call(api.GET('/api/v1/incidents/view-filters')),
    enabled,
  });
}

/** Your saved views and the shared ones, by name. */
export function useSavedViews(enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.savedViews,
    queryFn: () => call(api.GET('/api/v1/incidents/saved-views')),
    enabled,
  });
}

export type SavedViewChange =
  | { kind: 'create'; view: SavedViewInput }
  | { kind: 'update'; id: string; version: number; view: Partial<SavedViewInput> }
  | { kind: 'delete'; id: string; version: number };

/** Save, change or remove one of your views. */
export function useSavedViewChange() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (change: SavedViewChange): Promise<SavedView | null> => {
      if (change.kind === 'create') {
        return call(api.POST('/api/v1/incidents/saved-views', { body: change.view }));
      }
      if (change.kind === 'update') {
        return call(
          api.PATCH('/api/v1/incidents/saved-views/{view_id}', {
            params: { path: { view_id: change.id }, header: ifMatch(change.version) },
            body: change.view,
          }),
        );
      }
      await call(
        api.DELETE('/api/v1/incidents/saved-views/{view_id}', {
          params: { path: { view_id: change.id }, header: ifMatch(change.version) },
        }),
      );
      return null;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.savedViews });
    },
  });
}

/** The work-item lists that keep per-user, per-view settings (each type's `/list-settings`). */
export type WorkItemListKind =
  'incidents' | 'service-requests' | 'problems' | 'changes' | 'releases';
/**
 * Lists registered in the shared list-settings store (`/list-settings/{list_key}`, WP-049b s4a):
 * the same columns, sort and page size per view, plus saved views and favourites.
 */
export type SharedListKind = 'assets' | 'asset_consumables';
export type ListKind = WorkItemListKind | SharedListKind;

const SHARED: ReadonlySet<ListKind> = new Set<ListKind>(['assets', 'asset_consumables']);
const isShared = (kind: ListKind): kind is SharedListKind => SHARED.has(kind);

// Every type serves the same list-settings contract under its own path (work_items'
// add_list_routes), so the incidents path's types stand for all of them.
const settingsPath = (kind: WorkItemListKind) =>
  `/api/v1/${kind}/list-settings/{view_key}` as '/api/v1/incidents/list-settings/{view_key}';

/** The cache key of one list's settings for one view. */
export const listSettingKey = (kind: ListKind, viewKey: string) =>
  kind === 'incidents'
    ? queryKeys.incidents.listSetting(viewKey)
    : ([kind, 'list-settings', viewKey] as const);

// The shared store answers a superset (name, filter, favourite of a saved view): the widths and
// column code reads only what both have.
function getSetting(kind: ListKind, viewKey: string): Promise<ListSetting> {
  if (isShared(kind)) {
    return call(
      api.GET('/api/v1/list-settings/{list_key}/views/{view_key}', {
        params: { path: { list_key: kind, view_key: viewKey } },
      }),
    );
  }
  return call(api.GET(settingsPath(kind), { params: { path: { view_key: viewKey } } }));
}

function putSetting(
  kind: ListKind,
  viewKey: string,
  version: number | null,
  setting: ListSettingInput,
): Promise<ListSetting> {
  const header = version === null ? {} : ifMatch(version);
  if (isShared(kind)) {
    return call(
      api.PUT('/api/v1/list-settings/{list_key}/views/{view_key}', {
        params: { path: { list_key: kind, view_key: viewKey }, header },
        body: setting,
      }),
    );
  }
  return call(
    api.PUT(settingsPath(kind), { params: { path: { view_key: viewKey }, header }, body: setting }),
  );
}

/** Your columns, sort and page size for one view (`version` null: the defaults). */
export function useListSetting(viewKey: string, enabled = true, kind: ListKind = 'incidents') {
  return useQuery({
    queryKey: listSettingKey(kind, viewKey),
    queryFn: () => getSetting(kind, viewKey),
    enabled,
  });
}

interface SaveChain {
  running: Promise<unknown>;
  latest: number;
}
// One chain per signed-in session (its query client) and view key, shared by every caller in
// the page (QA10-P1-10); another view's saves run on their own chain.
const chains = new WeakMap<QueryClient, Map<string, SaveChain>>();

/**
 * Save your settings for one view; the first save has no version.
 *
 * Quick changes (three column moves in a row) must not race on If-Match (QA10-P1-10, as #234):
 * the screen shows each change at once (the cache is updated before the request), the saves run
 * one after another, a save overtaken by a newer one is skipped, and each sends the version the
 * previous save returned. These are your own settings, so a 409 from another tab is reconciled
 * by re-reading the version and saving yours once more (latest wins), never a conflict dialog.
 */
export interface SaveListSettingArgs {
  viewKey: string;
  setting: ListSettingInput;
}

export function useSaveListSetting(kind: ListKind = 'incidents') {
  const queryClient = useQueryClient();
  const keyOf = (viewKey: string) => listSettingKey(kind, viewKey);
  const put = (viewKey: string, version: number | null, setting: ListSettingInput) =>
    putSetting(kind, viewKey, version, setting);
  const save = async (viewKey: string, setting: ListSettingInput): Promise<ListSetting> => {
    const version = queryClient.getQueryData<ListSetting>(keyOf(viewKey))?.version ?? null;
    try {
      return await put(viewKey, version, setting);
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 409) throw error;
      // Another tab of yours saved first: take its version and save what you see now, your
      // latest action (lane A's review), so the other tab's change loses only to a newer one.
      const fresh = await getSetting(kind, viewKey);
      const shown = queryClient.getQueryData<ListSetting>(keyOf(viewKey));
      const latest: ListSettingInput =
        shown === undefined
          ? setting
          : { columns: shown.columns, sort: shown.sort, page_size: shown.page_size };
      return put(viewKey, fresh.version, latest);
    }
  };
  return useMutation({
    onMutate: ({ viewKey, setting }: SaveListSettingArgs) => {
      const before = queryClient.getQueryData<ListSetting>(keyOf(viewKey));
      if (before !== undefined)
        queryClient.setQueryData<ListSetting>(keyOf(viewKey), { ...before, ...setting });
    },
    mutationFn: ({ viewKey, setting }: SaveListSettingArgs): Promise<ListSetting | null> => {
      const mine = chains.get(queryClient) ?? new Map<string, SaveChain>();
      chains.set(queryClient, mine);
      const chainKey = `${kind}|${viewKey}`; // one chain per list and view
      const chain = mine.get(chainKey) ?? { running: Promise.resolve(), latest: 0 };
      mine.set(chainKey, chain);
      const ticket = ++chain.latest;
      const run = chain.running
        .catch(() => undefined)
        .then(async () => {
          if (ticket !== chain.latest) return null; // a newer change saves the final state
          const saved = await save(viewKey, setting);
          if (ticket === chain.latest) return saved;
          // A newer change is waiting: keep it on screen, carry only the new version forward.
          const shown = queryClient.getQueryData<ListSetting>(keyOf(viewKey));
          if (shown !== undefined)
            queryClient.setQueryData(keyOf(viewKey), { ...shown, version: saved.version });
          return null;
        });
      chain.running = run;
      return run;
    },
    onSuccess: (saved) => {
      // The last change's answer is the truth; an overtaken one already passed its version on.
      if (saved !== null) queryClient.setQueryData(keyOf(saved.view_key), saved);
    },
    onError: (_error, { viewKey }) => {
      void queryClient.invalidateQueries({ queryKey: keyOf(viewKey) });
    },
  });
}

/** The lists whose bulk jobs a screen follows: each type keeps its own jobs. */
export type BulkBase = 'incidents' | 'changes' | 'releases';

/** One bulk job's cache key, by the list it was started from. */
export const bulkJobKey = (base: BulkBase, id: string) =>
  base === 'incidents' ? queryKeys.incidents.bulkJob(id) : ([base, 'bulk-jobs', id] as const);

/** What a bulk job is asked for: picked rows, or every record of the list as shown. */
export interface BulkRequest {
  action: BulkAction;
  changes: Record<string, unknown>;
  /** Picked rows; leave out for "all matching" (the list query below decides). */
  recordIds?: string[];
  /** The list's own query, for "all matching". */
  query?: Pick<IncidentsQuery, 'view' | 'filter' | 'tag'>;
}

/** Queue a bulk job; progress arrives on your channel. */
export function useStartBulk(base: BulkBase = 'incidents') {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: BulkRequest) =>
      call(
        // Every type's bulk route has the incident route's shape; only the prefix differs.
        api.POST(`/api/v1/${base}/bulk` as '/api/v1/incidents/bulk', {
          params: {
            query:
              request.recordIds === undefined
                ? {
                    view: request.query?.view,
                    tag: request.query?.tag,
                    filter:
                      request.query?.filter === undefined
                        ? undefined
                        : JSON.stringify(request.query.filter),
                  }
                : {},
          },
          body: {
            action: request.action,
            changes: request.changes,
            record_ids: request.recordIds ?? [],
            all_matching: request.recordIds === undefined,
          },
        }),
      ),
    onSuccess: (job) => {
      queryClient.setQueryData(bulkJobKey(base, job.id), job);
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.bulkJobs });
    },
  });
}

/** One of your bulk jobs with its per-record results (incidents' by default; changes' too). */
export function useBulkJob(id: string | undefined, base: BulkBase = 'incidents') {
  return useQuery({
    queryKey: bulkJobKey(base, id ?? ''),
    queryFn: () => {
      const params = { params: { path: { job_id: id ?? '' } } };
      // Every type's job route has the incident route's shape; only the prefix differs.
      return call(
        api.GET(
          `/api/v1/${base}/bulk-jobs/{job_id}` as '/api/v1/incidents/bulk-jobs/{job_id}',
          params,
        ),
      );
    },
    enabled: id !== undefined,
    // Live through the personal channel; while it runs, also re-read now and then, so a job
    // that moved before the screen listened never stays at "waiting" (QA10-P1-09, rule 5c).
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? RUNNING_REFETCH_MS : false;
    },
  });
}

const RUNNING_REFETCH_MS = 5000;

/** Your latest bulk jobs, newest first (without results). */
export function useBulkJobs(enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.bulkJobs,
    queryFn: () => call(api.GET('/api/v1/incidents/bulk-jobs')),
    enabled,
  });
}
