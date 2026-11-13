import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { useSingleFlight } from './incidents';
import type { components } from './schema';

// Releases (WP-058a): a staged work item type (ADR-041). The record moves by listed status
// transitions shown on its stage rail; its own fields, roles, plan, schedule, downtimes,
// approvals and sub-releases each have their own resource and, where they can be edited at once
// by different people, their own version for If-Match.
export type Release = components['schemas']['WorkItemOut'];
export type ReleaseInput = components['schemas']['WorkItemIn'];
export type ReleaseListItem = components['schemas']['WorkItemListItem'];
export type StagePanel = components['schemas']['StagePanelOut'];
export type StageMove = components['schemas']['StageMoveOut'];
export type StageMoveInput = components['schemas']['StageMoveIn'];
export type RailStage = components['schemas']['RailStageOut'];
export type ReleaseDetails = components['schemas']['ReleaseDetailsOut'];
export type ReleaseDetailsInput = components['schemas']['ReleaseDetailsIn'];
export type RolesView = components['schemas']['RolesOut'];
export type RoleHolding = components['schemas']['RoleHoldingOut'];
export type PlanSection = components['schemas']['PlanSectionOut'];
export type StageSchedule = components['schemas']['StageScheduleOut'];
export type StageScheduleInput = components['schemas']['StageScheduleIn'];
export type Downtime = components['schemas']['DowntimeOut'];
export type DowntimeInput = components['schemas']['DowntimeIn'];
export type SubRelease = components['schemas']['SubReleaseOut'];
export type ReleaseTemplate = components['schemas']['TemplateOut'];
export type ReleaseApproval = components['schemas']['ApprovalOut'];
export type PersonOption = components['schemas']['PersonOptionOut'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

export const releaseKeys = {
  all: ['releases'] as const,
  list: (query: ReleasesQuery) => ['releases', 'list', query] as const,
  detail: (id: string) => ['releases', 'detail', id] as const,
  // Under the detail key: one invalidation of the record refreshes every part of it.
  part: (id: string, part: string) => ['releases', 'detail', id, part] as const,
  settings: ['releases', 'settings'] as const,
  templates: ['releases', 'templates'] as const,
  candidates: (role: string, search: string) => ['releases', 'candidates', role, search] as const,
};

export interface ReleasesQuery {
  view?: string;
  cursor?: string;
  /** The filter DSL as JSON (the list's search). */
  filter?: string;
  include_total?: boolean;
}

export function useReleases(query: ReleasesQuery) {
  return useQuery({
    queryKey: releaseKeys.list(query),
    queryFn: () => call(api.GET('/api/v1/releases', { params: { query } })),
    placeholderData: keepPreviousData,
  });
}

export function useRelease(id: string) {
  return useQuery({
    queryKey: releaseKeys.detail(id),
    queryFn: () =>
      call(api.GET('/api/v1/releases/{record_id}', { params: { path: { record_id: id } } })),
    enabled: id !== '',
  });
}

/** The type's configuration: statuses, the release type and reason lists (own_lists). */
export function useReleaseSettings() {
  return useQuery({
    queryKey: releaseKeys.settings,
    queryFn: () => call(api.GET('/api/v1/releases/settings')),
    staleTime: 60_000,
  });
}

export function useReleaseTemplates() {
  return useQuery({
    queryKey: releaseKeys.templates,
    queryFn: () => call(api.GET('/api/v1/releases/templates')),
    staleTime: 60_000,
  });
}

/** Create a release. One Idempotency-Key per form, so a retry never makes two (REQ-REL-007). */
export function useCreateRelease() {
  const queryClient = useQueryClient();
  const once = useSingleFlight(({ body, key }: { body: ReleaseInput; key: string }) =>
    call(api.POST('/api/v1/releases', { params: { header: { 'Idempotency-Key': key } }, body })),
  );
  return useMutation({
    mutationFn: once,
    onSuccess: (made) => {
      queryClient.setQueryData(releaseKeys.detail(made.id), made);
      void queryClient.invalidateQueries({ queryKey: [...releaseKeys.all, 'list'] });
    },
  });
}

/** The rail and the moves offered from the current status (ADR-041 §7). */
export function useStagePanel(id: string) {
  return useQuery({
    queryKey: releaseKeys.part(id, 'stages'),
    queryFn: () =>
      call(api.GET('/api/v1/releases/{record_id}/stages', { params: { path: { record_id: id } } })),
    enabled: id !== '',
  });
}

function useRefreshRecord() {
  const queryClient = useQueryClient();
  return (id: string) => {
    void queryClient.invalidateQueries({ queryKey: releaseKeys.detail(id) });
    void queryClient.invalidateQueries({ queryKey: [...releaseKeys.all, 'list'] });
  };
}

/** A listed move, with If-Match on the record and the values the move asks for. */
export function useMoveRelease() {
  const refresh = useRefreshRecord();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, version, body }: { id: string; version: number; body: StageMoveInput }) =>
      call(
        api.POST('/api/v1/releases/{record_id}/moves', {
          params: { path: { record_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    // The move's answer is the record now: show it at once, and stay busy until the rail and
    // the other parts have caught up, so the dialog never closes on a page that still shows the
    // old stage (QA10-P4-31).
    onSuccess: async (moved, { id }) => {
      queryClient.setQueryData(releaseKeys.detail(id), moved);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: releaseKeys.detail(id) }),
        queryClient.invalidateQueries({ queryKey: [...releaseKeys.all, 'list'] }),
      ]);
    },
    onError: (_error, { id }) => {
      refresh(id);
    },
  });
}

export function useReleaseDetails(id: string) {
  return useQuery({
    queryKey: releaseKeys.part(id, 'details'),
    queryFn: () =>
      call(
        api.GET('/api/v1/releases/{record_id}/details', { params: { path: { record_id: id } } }),
      ),
    enabled: id !== '',
  });
}

export function useUpdateReleaseDetails() {
  const refresh = useRefreshRecord();
  return useMutation({
    mutationFn: ({
      id,
      version,
      body,
    }: {
      id: string;
      version: number;
      body: ReleaseDetailsInput;
    }) =>
      call(
        api.PATCH('/api/v1/releases/{record_id}/details', {
          params: { path: { record_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    onSettled: (_data, _error, { id }) => {
      refresh(id);
    },
  });
}

export function useReleaseRoles(id: string) {
  return useQuery({
    queryKey: releaseKeys.part(id, 'roles'),
    queryFn: () =>
      call(api.GET('/api/v1/releases/{record_id}/roles', { params: { path: { record_id: id } } })),
    enabled: id !== '',
  });
}

export function useSetReleaseRole() {
  const refresh = useRefreshRecord();
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
        api.PUT('/api/v1/releases/{record_id}/roles/{role}', {
          params: { path: { record_id: id, role }, header: ifMatch(version) },
          body: { user_ids: userIds, group_ids: groupIds },
        }),
      ),
    onSettled: (_data, _error, { id }) => {
      refresh(id);
    },
  });
}

/** Only people the role allows (REQ-REL-024): the picker never offers anyone else. */
export function useRoleCandidates(role: string, search: string, enabled: boolean) {
  return useQuery({
    queryKey: releaseKeys.candidates(role, search),
    queryFn: () =>
      call(
        api.GET('/api/v1/releases/roles/{role}/candidates', {
          params: { path: { role }, query: { search: search === '' ? undefined : search } },
        }),
      ),
    enabled,
  });
}

export function usePlanSections(id: string) {
  return useQuery({
    queryKey: releaseKeys.part(id, 'plan'),
    queryFn: () =>
      call(api.GET('/api/v1/releases/{record_id}/plan', { params: { path: { record_id: id } } })),
    enabled: id !== '',
  });
}

/** One section, with that section's own If-Match (0: not written yet; REQ-REL-025). */
export function useWritePlanSection() {
  const queryClient = useQueryClient();
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
        api.PUT('/api/v1/releases/{record_id}/plan/{section}', {
          params: { path: { record_id: id, section }, header: ifMatch(version) },
          body: { content },
        }),
      ),
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: releaseKeys.part(id, 'plan') });
    },
  });
}

export function useStageSchedules(id: string) {
  return useQuery({
    queryKey: releaseKeys.part(id, 'schedule'),
    queryFn: () =>
      call(
        api.GET('/api/v1/releases/{record_id}/schedule', { params: { path: { record_id: id } } }),
      ),
    enabled: id !== '',
  });
}

export function useUpdateStageSchedule() {
  const queryClient = useQueryClient();
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
      body: StageScheduleInput;
    }) =>
      call(
        api.PATCH('/api/v1/releases/{record_id}/schedule/{stage}', {
          params: { path: { record_id: id, stage }, header: ifMatch(version) },
          body,
        }),
      ),
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: releaseKeys.part(id, 'schedule') });
    },
  });
}

export function useDowntimes(id: string) {
  return useQuery({
    queryKey: releaseKeys.part(id, 'downtimes'),
    queryFn: () =>
      call(
        api.GET('/api/v1/releases/{record_id}/downtimes', { params: { path: { record_id: id } } }),
      ),
    enabled: id !== '',
  });
}

/** Add a window (one Idempotency-Key per form) or change one (its own If-Match). */
export function useSaveDowntime() {
  const queryClient = useQueryClient();
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
      body: DowntimeInput;
    }) =>
      downtimeId === undefined
        ? call(
            api.POST('/api/v1/releases/{record_id}/downtimes', {
              params: { path: { record_id: id }, header: { 'Idempotency-Key': key ?? '' } },
              body,
            }),
          )
        : call(
            api.PATCH('/api/v1/releases/{record_id}/downtimes/{downtime_id}', {
              params: {
                path: { record_id: id, downtime_id: downtimeId },
                header: ifMatch(version ?? 0),
              },
              body,
            }),
          ),
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: releaseKeys.part(id, 'downtimes') });
    },
  });
}

export function useRemoveDowntime() {
  const queryClient = useQueryClient();
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
        api.DELETE('/api/v1/releases/{record_id}/downtimes/{downtime_id}', {
          params: { path: { record_id: id, downtime_id: downtimeId }, header: ifMatch(version) },
        }),
      );
    },
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: releaseKeys.part(id, 'downtimes') });
    },
  });
}

export function useReleaseApprovals(id: string) {
  return useQuery({
    queryKey: releaseKeys.part(id, 'approvals'),
    queryFn: () =>
      call(
        api.GET('/api/v1/releases/{record_id}/approvals', { params: { path: { record_id: id } } }),
      ),
    enabled: id !== '',
  });
}

/** Approve or reject with If-Match on the approval's version (REQ-REL-031). */
export function useDecideReleaseApproval() {
  const refresh = useRefreshRecord();
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
        api.POST('/api/v1/releases/{record_id}/approvals/{approval_id}/decision', {
          params: {
            path: { record_id: id, approval_id: approvalId },
            header: ifMatch(version),
          },
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

export function useSubReleases(id: string) {
  return useQuery({
    queryKey: releaseKeys.part(id, 'sub-releases'),
    queryFn: () =>
      call(
        api.GET('/api/v1/releases/{record_id}/sub-releases', {
          params: { path: { record_id: id } },
        }),
      ),
    enabled: id !== '',
  });
}

export function useSetParentRelease() {
  const refresh = useRefreshRecord();
  return useMutation({
    mutationFn: ({ id, parentId }: { id: string; parentId: string | null }) =>
      call(
        api.PUT('/api/v1/releases/{record_id}/parent', {
          params: { path: { record_id: id } },
          body: { parent_id: parentId },
        }),
      ),
    onSettled: (_data, _error, { id, parentId }) => {
      refresh(id);
      if (parentId !== null) refresh(parentId);
    },
  });
}

// --- changes in a release and the release calendar (WP-058b S1; REQ-REL-033, -027) ----------

export type ReleaseChange = components['schemas']['ReleaseChangeOut'];

/** The changes in a release; one you may not see shows only that it is there. */
export function useReleaseChanges(id: string) {
  return useQuery({
    queryKey: releaseKeys.part(id, 'changes'),
    queryFn: () =>
      call(
        api.GET('/api/v1/releases/{record_id}/changes', { params: { path: { record_id: id } } }),
      ),
    enabled: id !== '',
  });
}

/** Put a change in the release; a change in another open release is refused. */
export function useAddReleaseChange() {
  const refresh = useRefreshRecord();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, changeId }: { id: string; changeId: string }) => {
      await call(
        api.POST('/api/v1/releases/{record_id}/changes', {
          params: { path: { record_id: id } },
          body: { change_id: changeId },
        }),
      );
    },
    onSettled: (_data, _error, { id }) => {
      refresh(id);
      void queryClient.invalidateQueries({ queryKey: releaseKeys.part(id, 'changes') });
    },
  });
}

/** Take a change out of the release. */
export function useRemoveReleaseChange() {
  const refresh = useRefreshRecord();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, changeId }: { id: string; changeId: string }) => {
      await call(
        api.DELETE('/api/v1/releases/{record_id}/changes/{change_id}', {
          params: { path: { record_id: id, change_id: changeId } },
        }),
      );
    },
    onSettled: (_data, _error, { id }) => {
      refresh(id);
      void queryClient.invalidateQueries({ queryKey: releaseKeys.part(id, 'changes') });
    },
  });
}

export type LinkedChangeClosed = components['schemas']['LinkedChangeClosedOut'];

/**
 * Close the release's changes you may close (REQ-REL-052), each by its own close with this code;
 * the answer says, per change, closed or why not. The release's changes refetch.
 */
export function useCloseReleaseChanges() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, closureCode }: { id: string; closureCode: string }) =>
      call(
        api.POST('/api/v1/releases/{record_id}/changes/close', {
          params: { path: { record_id: id } },
          body: { closure_code: closureCode },
        }),
      ),
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: releaseKeys.part(id, 'changes') });
      void queryClient.invalidateQueries({ queryKey: ['changes'] });
    },
  });
}

export const releaseCalendarKeys = {
  all: ['release-calendar'] as const,
  range: (start: string, end: string, mine: boolean) =>
    ['release-calendar', start, end, mine] as const,
};

/** The releases you may see planned in [start, end): deployment windows and planned downtimes. */
export function useReleaseCalendar(start: string, end: string, mine: boolean, enabled = true) {
  return useQuery({
    queryKey: releaseCalendarKeys.range(start, end, mine),
    queryFn: () =>
      call(api.GET('/api/v1/release-calendar', { params: { query: { start, end, mine } } })),
    placeholderData: keepPreviousData,
    enabled,
  });
}

// --- a release's conflicts, acks and freeze override (WP-058b S2; REQ-REL-040, -041) --------

export type ReleaseConflicts = components['schemas']['ReleaseConflictsOut'];
export type ReleaseConflict = components['schemas']['ReleaseConflictOut'];

/** A release's conflicts now, each with its key, whether it blocks and its ack. */
export function useReleaseConflicts(id: string) {
  return useQuery({
    queryKey: releaseKeys.part(id, 'conflicts'),
    queryFn: () =>
      call(
        api.GET('/api/v1/releases/{record_id}/conflicts', { params: { path: { record_id: id } } }),
      ),
    enabled: id !== '',
  });
}

/** Acknowledge one warning with a reason (If-Match on the release). */
export function useAckReleaseConflict() {
  const refresh = useRefreshRecord();
  return useMutation({
    mutationFn: ({
      id,
      version,
      key,
      reason,
    }: {
      id: string;
      version: number;
      key: string;
      reason: string;
    }) =>
      call(
        api.POST('/api/v1/releases/{record_id}/conflicts/acks', {
          params: { path: { record_id: id }, header: ifMatch(version) },
          body: { key, reason },
        }),
      ),
    onSettled: (_data, _error, { id }) => {
      refresh(id);
    },
  });
}

/** Go ahead in these blocking freezes, with a reason (releases.override_freeze; If-Match). */
export function useReleaseFreezeOverride() {
  const refresh = useRefreshRecord();
  return useMutation({
    mutationFn: ({
      id,
      version,
      reason,
      windowIds,
    }: {
      id: string;
      version: number;
      reason: string;
      windowIds: string[];
    }) =>
      call(
        api.POST('/api/v1/releases/{record_id}/freeze-override', {
          params: { path: { record_id: id }, header: ifMatch(version) },
          body: { reason, window_ids: windowIds },
        }),
      ),
    onSettled: (_data, _error, { id }) => {
      refresh(id);
    },
  });
}

export type ReleaseFollowUpOut = components['schemas']['ReleaseFollowUpOut'];

/** What was made after the release failed: its problems and follow-up releases (REQ-REL-053). */
export function useReleaseFollowUps(id: string, enabled = true) {
  return useQuery({
    queryKey: releaseKeys.part(id, 'follow-ups'),
    queryFn: () =>
      call(
        api.GET('/api/v1/releases/{record_id}/follow-ups', {
          params: { path: { record_id: id } },
        }),
      ),
    enabled: enabled && id !== '',
  });
}

/** A problem caused by the failed release, or a release that follows it up (one at a time). */
export function useCreateReleaseFollowUp() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      kind,
      subject,
      key,
    }: {
      id: string;
      kind: 'problem' | 'release';
      subject: string;
      key: string;
    }) =>
      call(
        api.POST('/api/v1/releases/{record_id}/follow-ups', {
          params: { path: { record_id: id }, header: { 'Idempotency-Key': key } },
          body: { kind, subject },
        }),
      ),
    onSettled: (_out, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: releaseKeys.part(id, 'follow-ups') });
    },
  });
}
