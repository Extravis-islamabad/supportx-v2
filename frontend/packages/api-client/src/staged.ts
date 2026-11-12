import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import type { components } from './schema';
import type { StageMoveInput } from './releases';

// The stage engine's parts every staged type shares (ADR-041): releases and changes serve the
// same resources under their own path, with the same shapes. One hook per part, by type, so the
// change screens and the shared move dialog never copy the release hooks. The cache keys are
// the release keys' shape (`[path, 'detail', id, part]`), so one invalidation of a record
// refreshes every part of it, whichever hook wrote it.
export type StagedPath = 'releases' | 'changes';

// The path is a template literal at runtime; the typed client knows each type's own paths. The
// release paths stand for both: the shapes are one schema per part (StagePanelOut, RolesOut,
// PlanSectionOut, StageScheduleOut, DowntimeOut, ApprovalsOut), checked by the change tests.
const RECORD = '/api/v1/releases/{record_id}' as const;
type Part = `${typeof RECORD}/${string}` | `/api/v1/releases/${string}`;
const at = <P extends Part>(path: StagedPath, part: P): P =>
  part.replace('/api/v1/releases', `/api/v1/${path}`) as P;

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

export const stagedKeys = (path: StagedPath) => ({
  all: [path] as const,
  list: [path, 'list'] as const,
  detail: (id: string) => [path, 'detail', id] as const,
  part: (id: string, part: string) => [path, 'detail', id, part] as const,
  settings: [path, 'settings'] as const,
  candidates: (role: string, search: string) => [path, 'candidates', role, search] as const,
});

function useRefresh(path: StagedPath) {
  const queryClient = useQueryClient();
  const keys = stagedKeys(path);
  return (id: string) => {
    void queryClient.invalidateQueries({ queryKey: keys.detail(id) });
    void queryClient.invalidateQueries({ queryKey: keys.list });
  };
}

/** The type's configuration: statuses, closure codes and its own lists. */
export function useStagedSettings(path: StagedPath, enabled = true) {
  return useQuery({
    queryKey: stagedKeys(path).settings,
    queryFn: () => call(api.GET(at(path, '/api/v1/releases/settings'))),
    staleTime: 60_000,
    enabled,
  });
}

/** The rail and the moves offered, as query options: for a screen that asks on demand (a board). */
export function stagedPanelQuery(path: StagedPath, id: string) {
  return {
    queryKey: stagedKeys(path).part(id, 'stages'),
    queryFn: () =>
      call(api.GET(at(path, `${RECORD}/stages`), { params: { path: { record_id: id } } })),
  };
}

/** The rail and the moves offered from the current status (ADR-041 §7). */
export function useStagedPanel(path: StagedPath, id: string) {
  return useQuery({ ...stagedPanelQuery(path, id), enabled: id !== '' });
}

/** A listed move, with If-Match on the record and the values the move asks for. */
export function useStagedMove(path: StagedPath) {
  const queryClient = useQueryClient();
  const keys = stagedKeys(path);
  const refresh = useRefresh(path);
  return useMutation({
    mutationFn: ({ id, version, body }: { id: string; version: number; body: StageMoveInput }) =>
      call(
        api.POST(at(path, `${RECORD}/moves`), {
          params: { path: { record_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    // The answer is the record now; stay busy until the rail and the parts have caught up, so
    // the dialog never closes on a page that still shows the old stage (QA10-P4-31).
    onSuccess: async (moved, { id }) => {
      queryClient.setQueryData(keys.detail(id), moved);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.detail(id) }),
        queryClient.invalidateQueries({ queryKey: keys.list }),
      ]);
    },
    onError: (_error, { id }) => {
      refresh(id);
    },
  });
}

export function useStagedRoles(path: StagedPath, id: string) {
  return useQuery({
    queryKey: stagedKeys(path).part(id, 'roles'),
    queryFn: () =>
      call(api.GET(at(path, `${RECORD}/roles`), { params: { path: { record_id: id } } })),
    enabled: id !== '',
  });
}

export type RoleDefOut = components['schemas']['RoleDefOut'];

/**
 * A staged type's role definitions with the admin's own labels (the roles settings), for screens
 * that name its roles outside a record (a workflow's approval step). Reading needs the type's
 * settings view: without it the query fails quietly and callers label roles from their codes.
 */
export function useRoleDefs(path: StagedPath | undefined) {
  return useQuery({
    queryKey: [...stagedKeys(path ?? 'changes').settings, 'roles'] as const,
    queryFn: () => call(api.GET(at(path ?? 'changes', '/api/v1/releases/settings/roles'))),
    enabled: path !== undefined,
    retry: false,
    // A designer without the settings view gets a 403: labels fall back to the codes quietly,
    // never a global error toast (lane A's #420 review).
    meta: { silent: true },
  });
}

export function useSetStagedRole(path: StagedPath) {
  const refresh = useRefresh(path);
  return useMutation({
    mutationFn: ({
      id,
      role,
      version,
      userIds,
      groupIds = [],
    }: {
      id: string;
      role: string;
      version: number;
      userIds: string[];
      groupIds?: string[];
    }) =>
      call(
        api.PUT(at(path, `${RECORD}/roles/{role}`), {
          params: { path: { record_id: id, role }, header: ifMatch(version) },
          body: { user_ids: userIds, group_ids: groupIds },
        }),
      ),
    onSettled: (_data, _error, { id }) => {
      refresh(id);
    },
  });
}

/** Only people the role allows: the picker never offers anyone else. */
export function useStagedRoleCandidates(
  path: StagedPath,
  role: string,
  search: string,
  enabled: boolean,
) {
  return useQuery({
    queryKey: stagedKeys(path).candidates(role, search),
    queryFn: () =>
      call(
        api.GET(at(path, '/api/v1/releases/roles/{role}/candidates'), {
          params: { path: { role }, query: { search: search === '' ? undefined : search } },
        }),
      ),
    enabled,
  });
}

export function useStagedPlan(path: StagedPath, id: string) {
  return useQuery({
    queryKey: stagedKeys(path).part(id, 'plan'),
    queryFn: () =>
      call(api.GET(at(path, `${RECORD}/plan`), { params: { path: { record_id: id } } })),
    enabled: id !== '',
  });
}

/** One section, with that section's own If-Match (0: not written yet). */
export function useWriteStagedPlan(path: StagedPath) {
  const queryClient = useQueryClient();
  const keys = stagedKeys(path);
  return useMutation({
    mutationFn: ({
      id,
      section,
      version,
      content,
    }: {
      id: string;
      section: string;
      version: number;
      content: string | null;
    }) =>
      call(
        api.PUT(at(path, `${RECORD}/plan/{section}`), {
          params: { path: { record_id: id, section }, header: ifMatch(version) },
          body: { content },
        }),
      ),
    // The plan and the moves: a written backout plan unblocks "Send for approval".
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: keys.part(id, 'plan') });
      void queryClient.invalidateQueries({ queryKey: keys.part(id, 'stages') });
    },
  });
}

export function useStagedSchedule(path: StagedPath, id: string) {
  return useQuery({
    queryKey: stagedKeys(path).part(id, 'schedule'),
    queryFn: () =>
      call(api.GET(at(path, `${RECORD}/schedule`), { params: { path: { record_id: id } } })),
    enabled: id !== '',
  });
}

export function useStagedDowntimes(path: StagedPath, id: string) {
  return useQuery({
    queryKey: stagedKeys(path).part(id, 'downtimes'),
    queryFn: () =>
      call(api.GET(at(path, `${RECORD}/downtimes`), { params: { path: { record_id: id } } })),
    enabled: id !== '',
  });
}

export function useStagedApprovals(path: StagedPath, id: string) {
  return useQuery({
    queryKey: stagedKeys(path).part(id, 'approvals'),
    queryFn: () =>
      call(api.GET(at(path, `${RECORD}/approvals`), { params: { path: { record_id: id } } })),
    enabled: id !== '',
  });
}

/** Approve or reject with If-Match on the approval's version. */
export function useDecideStagedApproval(path: StagedPath) {
  const refresh = useRefresh(path);
  return useMutation({
    mutationFn: ({
      id,
      approvalId,
      version,
      decision,
      comment,
      isPrivate,
    }: {
      id: string;
      approvalId: string;
      version: number;
      decision: 'approve' | 'reject';
      comment?: string;
      isPrivate?: boolean;
    }) =>
      call(
        api.POST(at(path, `${RECORD}/approvals/{approval_id}/decision`), {
          params: { path: { record_id: id, approval_id: approvalId }, header: ifMatch(version) },
          body: {
            decision,
            comment: comment === undefined || comment === '' ? null : comment,
            private: isPrivate ?? false,
          },
        }),
      ),
    onSettled: (_data, _error, { id }) => {
      refresh(id);
    },
  });
}

/** One stage's dates or outcome, with that stage's own If-Match. */
export function useUpdateStagedSchedule(path: StagedPath) {
  const queryClient = useQueryClient();
  const keys = stagedKeys(path);
  return useMutation({
    mutationFn: ({
      id,
      stage,
      version,
      body,
    }: {
      id: string;
      stage: string;
      version: number;
      body: components['schemas']['StageScheduleIn'];
    }) =>
      call(
        api.PATCH(at(path, `${RECORD}/schedule/{stage}`), {
          params: { path: { record_id: id, stage }, header: ifMatch(version) },
          body,
        }),
      ),
    // The schedule and the moves: an outcome unblocks completing the stage.
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: keys.part(id, 'schedule') });
      void queryClient.invalidateQueries({ queryKey: keys.part(id, 'stages') });
      void queryClient.invalidateQueries({ queryKey: keys.part(id, 'conflicts') });
    },
  });
}

/** Add a window (one Idempotency-Key per form) or change one (its own If-Match). */
export function useSaveStagedDowntime(path: StagedPath) {
  const queryClient = useQueryClient();
  const keys = stagedKeys(path);
  return useMutation({
    mutationFn: ({
      id,
      downtimeId,
      version,
      key,
      body,
    }: {
      id: string;
      downtimeId?: string;
      version?: number;
      key?: string;
      body: components['schemas']['DowntimeIn'];
    }) =>
      downtimeId === undefined
        ? call(
            api.POST(at(path, `${RECORD}/downtimes`), {
              params: { path: { record_id: id }, header: { 'Idempotency-Key': key ?? '' } },
              body,
            }),
          )
        : call(
            api.PATCH(at(path, `${RECORD}/downtimes/{downtime_id}`), {
              params: {
                path: { record_id: id, downtime_id: downtimeId },
                header: ifMatch(version ?? 0),
              },
              body,
            }),
          ),
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: keys.part(id, 'downtimes') });
      void queryClient.invalidateQueries({ queryKey: keys.part(id, 'conflicts') });
    },
  });
}

export function useRemoveStagedDowntime(path: StagedPath) {
  const queryClient = useQueryClient();
  const keys = stagedKeys(path);
  return useMutation({
    mutationFn: async ({
      id,
      downtimeId,
      version,
    }: {
      id: string;
      downtimeId: string;
      version: number;
    }) => {
      await call(
        api.DELETE(at(path, `${RECORD}/downtimes/{downtime_id}`), {
          params: { path: { record_id: id, downtime_id: downtimeId }, header: ifMatch(version) },
        }),
      );
    },
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: keys.part(id, 'downtimes') });
      void queryClient.invalidateQueries({ queryKey: keys.part(id, 'conflicts') });
    },
  });
}
