import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { useSingleFlight } from './incidents';
import { bulkJobKey } from './incidentLists';
import type { components } from './schema';
import { stagedKeys } from './staged';

// Changes (WP-045a/b): a staged work item type on the stage engine (ADR-041). The parts every
// staged type shares (rail, moves, roles, plan, schedule, downtimes, approvals) are in staged.ts;
// these are a change's own: its fields, its risk questionnaire, the list and the form.
export type Change = components['schemas']['WorkItemOut'];
export type ChangeInput = components['schemas']['WorkItemIn'];
export type ChangeListItem = components['schemas']['WorkItemListItem'];
export type ChangeDetails = components['schemas']['ChangeDetailsOut'];
export type ChangeDetailsInput = components['schemas']['ChangeDetailsIn'];
export type ChangeRiskQuestionnaire = components['schemas']['ChangeRiskQuestionnaireOut'];
export type ChangeTemplate = components['schemas']['TemplateOut'];
export type ChangePrefill = components['schemas']['ChangePrefillOut'];
export type RiskLevel = components['schemas']['RiskLevel'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });
const keys = stagedKeys('changes');

export const changeKeys = {
  ...keys,
  query: (query: ChangesQuery) => ['changes', 'list', query] as const,
  views: ['changes', 'list', 'views'] as const,
  templates: ['changes', 'templates'] as const,
  prefill: (from: string) => ['changes', 'prefill', from] as const,
};

export interface ChangesQuery {
  view?: string;
  cursor?: string;
  /** The filter DSL as JSON (the list's search). */
  filter?: string;
  include_total?: boolean;
}

export function useChanges(query: ChangesQuery) {
  return useQuery({
    queryKey: changeKeys.query(query),
    queryFn: () => call(api.GET('/api/v1/changes', { params: { query } })),
    placeholderData: keepPreviousData,
  });
}

/** The built-in views this person may use, in the menu's order, with their counts. */
export function useChangeViews() {
  return useQuery({
    queryKey: changeKeys.views,
    queryFn: () => call(api.GET('/api/v1/changes/views')),
    staleTime: 30_000,
  });
}

export function useChange(id: string) {
  return useQuery({
    queryKey: keys.detail(id),
    queryFn: () =>
      call(api.GET('/api/v1/changes/{record_id}', { params: { path: { record_id: id } } })),
    enabled: id !== '',
  });
}

export function useChangeTemplates() {
  return useQuery({
    queryKey: changeKeys.templates,
    queryFn: () => call(api.GET('/api/v1/changes/templates')),
    staleTime: 60_000,
  });
}

/** A new change's values from the incident, request, problem or release it is raised from. */
export function useChangePrefill(from: string | null) {
  return useQuery({
    queryKey: changeKeys.prefill(from ?? ''),
    queryFn: () =>
      call(api.GET('/api/v1/changes/prefill', { params: { query: { record_id: from ?? '' } } })),
    enabled: from !== null && from !== '',
  });
}

/** Create a change. One Idempotency-Key per form, so a retry never makes two. */
export function useCreateChange() {
  const queryClient = useQueryClient();
  const once = useSingleFlight(({ body, key }: { body: ChangeInput; key: string }) =>
    call(api.POST('/api/v1/changes', { params: { header: { 'Idempotency-Key': key } }, body })),
  );
  return useMutation({
    mutationFn: once,
    onSuccess: (made) => {
      queryClient.setQueryData(keys.detail(made.id), made);
      void queryClient.invalidateQueries({ queryKey: keys.list });
    },
  });
}

/** The record's own fields (subject, description, people) with the record's If-Match. */
export function useEditChange() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      version,
      body,
    }: {
      id: string;
      version: number;
      body: components['schemas']['WorkItemPatch'];
    }) =>
      call(
        api.PATCH('/api/v1/changes/{record_id}', {
          params: { path: { record_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    onSuccess: (saved, { id }) => {
      queryClient.setQueryData(keys.detail(id), saved);
    },
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: keys.detail(id) });
      void queryClient.invalidateQueries({ queryKey: keys.list });
    },
  });
}

export function useChangeDetails(id: string) {
  return useQuery({
    queryKey: keys.part(id, 'details'),
    queryFn: () =>
      call(api.GET('/api/v1/changes/{record_id}/details', { params: { path: { record_id: id } } })),
    enabled: id !== '',
  });
}

/** Type, reason and a person's risk override (which always says why), with its own version. */
export function useUpdateChangeDetails() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      version,
      body,
    }: {
      id: string;
      version: number;
      body: ChangeDetailsInput;
    }) =>
      call(
        api.PATCH('/api/v1/changes/{record_id}/details', {
          params: { path: { record_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: keys.detail(id) });
      void queryClient.invalidateQueries({ queryKey: keys.list });
    },
  });
}

/** The questionnaire this change is assessed with (its template's, else the default one). */
export function useChangeRiskQuestionnaire(id: string) {
  return useQuery({
    queryKey: keys.part(id, 'risk'),
    queryFn: () =>
      call(
        api.GET('/api/v1/changes/{record_id}/risk/questionnaire', {
          params: { path: { record_id: id } },
        }),
      ),
    enabled: id !== '',
  });
}

/** One answer per question; the server scores it and sets the level (with the details' version). */
export function useAssessChangeRisk() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      version,
      answers,
    }: {
      id: string;
      version: number;
      answers: Record<string, string>;
    }) =>
      call(
        api.PUT('/api/v1/changes/{record_id}/risk/assessment', {
          params: { path: { record_id: id }, header: ifMatch(version) },
          body: { answers },
        }),
      ),
    onSuccess: (details, { id }) => {
      queryClient.setQueryData(keys.part(id, 'details'), details);
    },
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: keys.detail(id) });
      void queryClient.invalidateQueries({ queryKey: keys.list });
    },
  });
}

export type ChangeApprovalPreview = components['schemas']['ChangeApprovalPreviewOut'];
export type StageChanges = components['schemas']['StageChangesOut'];
export type ChangeBoard = components['schemas']['BoardOut'];
export type ChangeBoardInput = components['schemas']['BoardIn'];
export type ChangeBoardPatch = components['schemas']['BoardPatch'];

/** Before a submit: who would approve the stage, who is left out and why (REQ-CHG-039). */
export function useChangeApprovalPreview(id: string, stage: string | null, enabled: boolean) {
  return useQuery({
    queryKey: [...keys.part(id, 'approval-preview'), stage ?? ''],
    queryFn: () =>
      call(
        api.GET('/api/v1/changes/{record_id}/approvals/preview', {
          params: { path: { record_id: id }, query: { stage: stage ?? undefined } },
        }),
      ),
    enabled: id !== '' && enabled,
  });
}

/** Per approved stage, field by field, what changed since and what each change does. */
export function useChangesSinceApproval(id: string) {
  return useQuery({
    queryKey: keys.part(id, 'changes-since'),
    queryFn: () =>
      call(
        api.GET('/api/v1/changes/{record_id}/approvals/changes-since', {
          params: { path: { record_id: id } },
        }),
      ),
    enabled: id !== '',
  });
}

/** Keep a change going that was sent back for approval: a permission and a reason (D-144). */
export function useEmergencyOverride() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, version, reason }: { id: string; version: number; reason: string }) =>
      call(
        api.POST('/api/v1/changes/{record_id}/emergency-override', {
          params: { path: { record_id: id }, header: ifMatch(version) },
          body: { reason },
        }),
      ),
    onSuccess: (moved, { id }) => {
      queryClient.setQueryData(keys.detail(id), moved);
    },
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: keys.detail(id) });
      void queryClient.invalidateQueries({ queryKey: keys.list });
    },
  });
}

const boardKeys = {
  all: ['change-boards'] as const,
  one: (id: string) => ['change-boards', id] as const,
};

/** The tenant's change advisory boards, in their order (WP-045b S2). */
export function useChangeBoards() {
  return useQuery({
    queryKey: boardKeys.all,
    queryFn: () => call(api.GET('/api/v1/change-boards')),
  });
}

/** Add a board (one Idempotency-Key per form). */
export function useCreateChangeBoard() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ body, key }: { body: ChangeBoardInput; key: string }) =>
      call(
        api.POST('/api/v1/change-boards', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: boardKeys.all });
    },
  });
}

/** Change a board with its own If-Match (members, chair, rule, mapping, order). */
export function useUpdateChangeBoard() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, version, body }: { id: string; version: number; body: ChangeBoardPatch }) =>
      call(
        api.PATCH('/api/v1/change-boards/{board_id}', {
          params: { path: { board_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: boardKeys.all });
    },
  });
}

/** Remove a board (never the default one; the server says why). */
export function useRemoveChangeBoard() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, version }: { id: string; version: number }) => {
      await call(
        api.DELETE('/api/v1/change-boards/{board_id}', {
          params: { path: { board_id: id }, header: ifMatch(version) },
        }),
      );
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: boardKeys.all });
    },
  });
}

/** Would this window or risk send the change back for approval? Changes nothing (REQ-CHG-053). */
export function useReapprovalPreview() {
  return useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: string;
      body: components['schemas']['ReapprovalPreviewIn'];
    }) =>
      call(
        api.POST('/api/v1/changes/{record_id}/approvals/reapproval-preview', {
          params: { path: { record_id: id } },
          body,
        }),
      ),
  });
}

export type ChangeChild = components['schemas']['ChildOut'];

/** The change's child changes and releases (those you may see); closing waits for them. */
export function useChangeChildren(id: string) {
  return useQuery({
    queryKey: keys.part(id, 'children'),
    queryFn: () =>
      call(
        api.GET('/api/v1/changes/{record_id}/children', { params: { path: { record_id: id } } }),
      ),
    enabled: id !== '',
  });
}

export type ChangeConflicts = components['schemas']['ConflictsOut'];
export type ChangeConflict = components['schemas']['ConflictOut'];
export type ChangeWindow = components['schemas']['WindowOut'];

/** A change's conflicts now (freezes, outside maintenance, overlapping changes), each with why. */
export function useChangeConflicts(id: string) {
  return useQuery({
    queryKey: keys.part(id, 'conflicts'),
    queryFn: () =>
      call(
        api.GET('/api/v1/changes/{record_id}/conflicts', { params: { path: { record_id: id } } }),
      ),
    enabled: id !== '',
  });
}

/** Make a change or a release, found by its number, part of this change. */
export function useAddChangeChild() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, number }: { id: string; number: string }) => {
      const value = number.trim().toUpperCase();
      // A release's number reads REL-…, a change's CHG-…: each type finds its own.
      const found = value.startsWith('REL')
        ? await call(api.GET('/api/v1/releases/lookup/{value}', { params: { path: { value } } }))
        : await call(api.GET('/api/v1/changes/lookup/{value}', { params: { path: { value } } }));
      return call(
        api.POST('/api/v1/changes/{record_id}/children', {
          params: { path: { record_id: id } },
          body: { child_id: found.id },
        }),
      );
    },
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: keys.part(id, 'children') });
    },
  });
}

export function useRemoveChangeChild() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, linkId }: { id: string; linkId: string }) => {
      await call(
        api.DELETE('/api/v1/changes/{record_id}/children/{link_id}', {
          params: { path: { record_id: id, link_id: linkId } },
        }),
      );
    },
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: keys.part(id, 'children') });
    },
  });
}

/**
 * Close the picked changes in one background job (REQ-CHG-101): each by its own move to closed,
 * with the closure code and closing description; any that may not close is skipped, with why.
 * Progress arrives on your channel (the shared bulk drawer, base "changes").
 */
export function useStartChangeBulkClose() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: { recordIds: string[]; closureCode: string; resolution?: string }) =>
      call(
        api.POST('/api/v1/changes/bulk', {
          body: {
            action: 'close',
            changes: {
              closure_code: request.closureCode,
              ...(request.resolution ? { resolution: request.resolution } : {}),
            },
            record_ids: request.recordIds,
            all_matching: false,
          },
        }),
      ),
    onSuccess: (job) => {
      queryClient.setQueryData(bulkJobKey('changes', job.id), job);
    },
  });
}

/** Cancel the picked changes with one reason, or move them to the trash (REQ-CHG-101). */
export function useStartChangeBulk() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: { action: 'cancel' | 'delete'; recordIds: string[]; reason?: string }) =>
      call(
        api.POST('/api/v1/changes/bulk', {
          body: {
            action: request.action,
            changes: request.action === 'cancel' ? { reason_text: request.reason ?? '' } : {},
            record_ids: request.recordIds,
            all_matching: false,
          },
        }),
      ),
    onSuccess: (job) => {
      queryClient.setQueryData(bulkJobKey('changes', job.id), job);
    },
  });
}

/** The freeze and maintenance windows; with a range, only those then (the calendar). */
export function useChangeWindows(range?: { start: string; end: string }) {
  return useQuery({
    queryKey: ['change-windows', range?.start ?? '', range?.end ?? ''],
    queryFn: () => call(api.GET('/api/v1/change-windows', { params: { query: range ?? {} } })),
  });
}

/** Go ahead in these blocking freezes, with a reason (changes.override_freeze; ADR-042). */
export function useFreezeOverride() {
  const queryClient = useQueryClient();
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
        api.POST('/api/v1/changes/{record_id}/freeze-override', {
          params: { path: { record_id: id }, header: ifMatch(version) },
          body: { reason, window_ids: windowIds },
        }),
      ),
    onSettled: (_data, _error, { id }) => {
      void queryClient.invalidateQueries({ queryKey: keys.detail(id) });
    },
  });
}

export type CalendarEntry = components['schemas']['CalendarEntryOut'];
export type ChangeWindowInput = components['schemas']['WindowIn'];
export type ChangeWindowPatch = components['schemas']['WindowPatch'];

export const calendarKeys = {
  all: ['change-calendar'] as const,
  range: (start: string, end: string, mine: boolean) =>
    ['change-calendar', start, end, mine] as const,
};
const windowKeys = { all: ['change-windows'] as const };

/** The changes you may see planned in [start, end): windows and planned downtimes. */
export function useChangeCalendar(start: string, end: string, mine: boolean) {
  return useQuery({
    queryKey: calendarKeys.range(start, end, mine),
    queryFn: () =>
      call(api.GET('/api/v1/change-calendar', { params: { query: { start, end, mine } } })),
    placeholderData: keepPreviousData,
  });
}

/** Add a window (one Idempotency-Key per form). */
export function useCreateChangeWindow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ body, key }: { body: ChangeWindowInput; key: string }) =>
      call(
        api.POST('/api/v1/change-windows', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: windowKeys.all });
    },
  });
}

/** Change a window with its own If-Match. */
export function useUpdateChangeWindow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, version, body }: { id: string; version: number; body: ChangeWindowPatch }) =>
      call(
        api.PATCH('/api/v1/change-windows/{window_id}', {
          params: { path: { window_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: windowKeys.all });
    },
  });
}

/** Remove a window (its history stays). */
export function useRemoveChangeWindow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, version }: { id: string; version: number }) => {
      await call(
        api.DELETE('/api/v1/change-windows/{window_id}', {
          params: { path: { window_id: id }, header: ifMatch(version) },
        }),
      );
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: windowKeys.all });
    },
  });
}

/**
 * Change the change type's settings with the If-Match the screen showed (D-156: whether
 * outside-maintenance blocks); the answer replaces the cached settings at once.
 */
export function useChangeSettingsChange() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      body,
      version,
    }: {
      body: Partial<components['schemas']['WorkItemSettingsPatch']>;
      version: number;
    }) =>
      call(
        api.PATCH('/api/v1/changes/settings', {
          params: { header: ifMatch(version) },
          body,
        }),
      ),
    onSuccess: (settings) => {
      queryClient.setQueryData(stagedKeys('changes').settings, settings);
    },
  });
}
