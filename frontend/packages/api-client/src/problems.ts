import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { useSingleFlight, type ActionRun, type AssignChange } from './incidents';
import type { FilterExpression } from './users';
import type { components } from './schema';

// Problems (WP-044a): a work item of its own type on the same engine. This file covers what the
// console needs for creating and working problems: the list, one record and its moves, creating
// (also from incidents and as a copy), similar problems, the caused incidents and investigators.
export type Problem = components['schemas']['WorkItemOut'];
export type ProblemInput = components['schemas']['WorkItemIn'];
export type ProblemCatalogue = components['schemas']['WorkItemCatalogueOut'];
export type ProblemTemplate = components['schemas']['TemplateOut'];
export type ProblemPrefill = components['schemas']['ProblemPrefillOut'];
export type SimilarProblem = components['schemas']['SimilarProblemOut'];
export type ProblemLink = components['schemas']['WorkItemLinkOut'];
export type ProblemPatch = Partial<components['schemas']['WorkItemPatch']>;
export type ProblemImpact = components['schemas']['ProblemImpactOut'];
export type ProblemEvidence = components['schemas']['ProblemEvidenceOut'];

export interface ProblemsQuery {
  view?: string;
  cursor?: string;
  /** The shared filter DSL (search words, a display ID). */
  filter?: FilterExpression;
  sort?: string;
}

export const problemKeys = {
  all: ['problems'] as const,
  list: (query: ProblemsQuery) => ['problems', 'list', query] as const,
  views: ['problems', 'views'] as const,
  repeats: ['problems', 'repeats'] as const,
  repeatIncidents: (hitId: string) => ['problems', 'repeats', hitId, 'incidents'] as const,
  detail: (id: string) => ['problems', 'detail', id] as const,
  links: (id: string) => ['problems', 'detail', id, 'links'] as const,
  investigators: (id: string) => ['problems', 'detail', id, 'investigators'] as const,
  impact: (id: string) => ['problems', 'detail', id, 'impact'] as const,
  evidence: (id: string) => ['problems', 'detail', id, 'evidence'] as const,
  settings: ['problems', 'settings'] as const,
  templates: ['problems', 'templates'] as const,
  similar: (q: string) => ['problems', 'similar', q] as const,
  prefill: (incidentId: string) => ['problems', 'prefill', incidentId] as const,
};

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

export function useProblems(query: ProblemsQuery) {
  return useQuery({
    queryKey: problemKeys.list(query),
    queryFn: () =>
      call(
        api.GET('/api/v1/problems', {
          params: {
            query: {
              view: query.view,
              cursor: query.cursor,
              sort: query.sort,
              filter: query.filter === undefined ? undefined : JSON.stringify(query.filter),
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

/** The built-in problem views in their fixed order, each with how many you see (WP-044c). */
export function useProblemViews() {
  return useQuery({
    queryKey: problemKeys.views,
    queryFn: () => call(api.GET('/api/v1/problems/views')),
    // "Accepted, due for review" changes with the clock, not only with events.
    refetchInterval: 60_000,
  });
}

export function useProblem(id: string) {
  return useQuery({
    queryKey: problemKeys.detail(id),
    queryFn: () =>
      call(api.GET('/api/v1/problems/{record_id}', { params: { path: { record_id: id } } })),
    enabled: id !== '',
  });
}

/** The problem type's settings: statuses, every transition set, actions, lists (cached). */
export function useProblemCatalogue(enabled = true) {
  return useQuery({
    queryKey: problemKeys.settings,
    queryFn: () => call(api.GET('/api/v1/problems/settings')),
    enabled,
    staleTime: 60_000,
  });
}

export function useProblemTemplates(enabled = true) {
  return useQuery({
    enabled,
    queryKey: problemKeys.templates,
    queryFn: () => call(api.GET('/api/v1/problems/templates')),
    staleTime: 60_000,
  });
}

/** A new problem's values from an incident (REQ-PRB-011): shown, changed, then saved. */
export function useProblemPrefill(incidentId: string | undefined) {
  return useQuery({
    queryKey: problemKeys.prefill(incidentId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/problems/prefill', {
          params: { query: { incident_id: incidentId ?? '' } },
        }),
      ),
    enabled: incidentId !== undefined && incidentId !== '',
  });
}

/** Open problems like the draft title (REQ-PRB-014); nothing for fewer than 3 characters. */
export function useSimilarProblems(q: string) {
  const text = q.trim();
  return useQuery({
    queryKey: problemKeys.similar(text),
    queryFn: () => call(api.GET('/api/v1/problems/similar', { params: { query: { q: text } } })),
    enabled: text.length >= 3,
    placeholderData: keepPreviousData,
    meta: { silent: true },
  });
}

/** The selected incidents already caused by a problem (REQ-PRB-012 AC2), listed first. */
export function useFromIncidentsPreview(incidentIds: string[]) {
  return useQuery({
    queryKey: ['problems', 'from-incidents', incidentIds],
    queryFn: () =>
      call(
        api.POST('/api/v1/problems/from-incidents/preview', {
          body: { incident_ids: incidentIds },
        }),
      ),
    enabled: incidentIds.length > 0,
  });
}

function useSavedProblem() {
  const queryClient = useQueryClient();
  return (saved: Problem) => {
    queryClient.setQueryData(problemKeys.detail(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: [...problemKeys.all, 'list'] });
  };
}

/** Give a problem to a group and an owner (WP-044c S1); the same rules as an incident's. */
export function useAssignProblem(id: string) {
  const saved = useSavedProblem();
  const queryClient = useQueryClient();
  const once = useSingleFlight((change: AssignChange) =>
    call(
      api.POST('/api/v1/problems/{record_id}/assign', {
        params: { path: { record_id: id }, header: ifMatch(change.version) },
        body: {
          group_id: change.groupId,
          technician_id: change.technicianId,
          reason_code: change.reasonCode ?? null,
          reason_text: change.reasonText?.trim() === '' ? null : (change.reasonText ?? null),
          confirm_lose_access: change.confirmLoseAccess ?? false,
          keep_following: change.keepFollowing ?? null,
        },
      }),
    ),
  );
  return useMutation({
    meta: { silent: true },
    mutationFn: once,
    onSuccess: saved,
    onError: (error) => {
      if (error instanceof ApiError && error.isConflict) {
        void queryClient.invalidateQueries({ queryKey: problemKeys.detail(id) });
      }
    },
  });
}

export function useCreateProblem() {
  const saved = useSavedProblem();
  const once = useSingleFlight(({ body, key }: { body: ProblemInput; key: string }) =>
    call(api.POST('/api/v1/problems', { params: { header: { 'Idempotency-Key': key } }, body })),
  );
  return useMutation({ meta: { silent: true }, mutationFn: once, onSuccess: saved });
}

export interface FromIncidents {
  body: ProblemInput;
  mainIncidentId: string;
  incidentIds: string[];
  moveIncidentIds: string[];
  key: string;
}

/** One problem from incidents: the main one linked now, the rest by background job (AC1). */
export function useCreateProblemFromIncidents() {
  const saved = useSavedProblem();
  const queryClient = useQueryClient();
  const once = useSingleFlight((run: FromIncidents) =>
    call(
      api.POST('/api/v1/problems/from-incidents', {
        params: { header: { 'Idempotency-Key': run.key } },
        body: {
          problem: run.body,
          main_incident_id: run.mainIncidentId,
          incident_ids: run.incidentIds,
          move_incident_ids: run.moveIncidentIds,
        },
      }),
    ),
  );
  return useMutation({
    meta: { silent: true },
    mutationFn: once,
    onSuccess: (made) => {
      saved(made.problem);
      void queryClient.invalidateQueries({ queryKey: ['incidents'] });
    },
  });
}

/** Copy a problem (REQ-PRB-015): its fields, a marked title, the original named in history. */
export function useCopyProblem() {
  const saved = useSavedProblem();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, key }: { id: string; key: string }) =>
      call(
        api.POST('/api/v1/problems/{record_id}/copy', {
          params: { path: { record_id: id }, header: { 'Idempotency-Key': key } },
        }),
      ),
    onSuccess: saved,
  });
}

/** Run a life cycle action with If-Match (the same input as an incident's, so the status bar
 * and its dialogs are shared); a 409 refetches the record for the conflict dialog. */
export function useProblemAction(id: string) {
  const saved = useSavedProblem();
  const queryClient = useQueryClient();
  const once = useSingleFlight((run: ActionRun) => {
    const text = run.reasonText?.trim() ?? '';
    const plain =
      run.reasonCode === undefined &&
      text === '' &&
      run.resolution === undefined &&
      run.closureCode === undefined &&
      run.confirmOpenWork !== true;
    return call(
      api.POST('/api/v1/problems/{record_id}/actions/{action}', {
        params: { path: { record_id: id, action: run.action }, header: ifMatch(run.version) },
        body: plain
          ? undefined
          : {
              reason_code: run.reasonCode ?? null,
              reason_text: text === '' ? null : text,
              confirm_open_work: run.confirmOpenWork === true,
              ...(run.resolution === undefined ? {} : { resolution: run.resolution }),
              ...(run.closureCode === undefined ? {} : { closure_code: run.closureCode }),
            },
      }),
    );
  });
  return useMutation({
    meta: { silent: true },
    mutationFn: once,
    onSuccess: saved,
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.isConflict) {
        void queryClient.invalidateQueries({ queryKey: problemKeys.detail(id) });
      }
    },
  });
}

/** The record's links: caused incidents show as `causes` with the incident's type. */
export function useProblemLinks(id: string) {
  return useQuery({
    queryKey: problemKeys.links(id),
    queryFn: () =>
      call(api.GET('/api/v1/problems/{record_id}/links', { params: { path: { record_id: id } } })),
    enabled: id !== '',
  });
}

/** Link one incident (409 `incident_has_problem` names its problem unless `move`). */
export function useLinkIncident(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ incidentId, move }: { incidentId: string; move: boolean }) =>
      call(
        api.POST('/api/v1/problems/{record_id}/incidents', {
          params: { path: { record_id: id } },
          body: { incident_id: incidentId, move },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: problemKeys.links(id) });
    },
  });
}

export function useInvestigators(id: string) {
  return useQuery({
    queryKey: problemKeys.investigators(id),
    queryFn: () =>
      call(
        api.GET('/api/v1/problems/{record_id}/investigators', {
          params: { path: { record_id: id } },
        }),
      ),
    enabled: id !== '',
  });
}

/** Name or remove an investigator (ADR-040): they reach this problem's notes, tasks, worklogs. */
export function useInvestigatorChange(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: async ({ userId, add }: { userId: string; add: boolean }) => {
      const params = { path: { record_id: id, user_id: userId } };
      if (add)
        await call(api.PUT('/api/v1/problems/{record_id}/investigators/{user_id}', { params }));
      else
        await call(api.DELETE('/api/v1/problems/{record_id}/investigators/{user_id}', { params }));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: problemKeys.investigators(id) });
    },
  });
}

/** Technicians who work on problems, to name as investigators (holders of `problems.view`). */
export function useProblemPeople(id: string, search: string) {
  return useQuery({
    queryKey: ['problems', 'detail', id, 'people', search],
    queryFn: () =>
      call(
        api.GET('/api/v1/problems/{record_id}/mentionable', {
          params: { path: { record_id: id }, query: { search: search.trim() || undefined } },
        }),
      ),
    enabled: id !== '',
    placeholderData: keepPreviousData,
  });
}

/** Change a problem's fields with If-Match (409 `version_conflict` names what changed). */
export function useUpdateProblem(id: string) {
  const saved = useSavedProblem();
  const once = useSingleFlight(({ changes, version }: { changes: ProblemPatch; version: number }) =>
    call(
      api.PATCH('/api/v1/problems/{record_id}', {
        params: { path: { record_id: id }, header: ifMatch(version) },
        body: { confirm_lose_access: false, ...changes },
      }),
    ),
  );
  return useMutation({ meta: { silent: true }, mutationFn: once, onSuccess: saved });
}

/** Figures from the caused incidents you may see (REQ-PRB-033); `partial` when some are not. */
export function useProblemImpact(id: string) {
  return useQuery({
    queryKey: problemKeys.impact(id),
    queryFn: () =>
      call(api.GET('/api/v1/problems/{record_id}/impact', { params: { path: { record_id: id } } })),
    enabled: id !== '',
  });
}

/** The evidence timeline (REQ-PRB-032) and the sources not there yet. */
export function useProblemEvidence(id: string) {
  return useQuery({
    queryKey: problemKeys.evidence(id),
    queryFn: () =>
      call(
        api.GET('/api/v1/problems/{record_id}/evidence', { params: { path: { record_id: id } } }),
      ),
    enabled: id !== '',
  });
}

/** Unlink one incident (needs that incident's edit right; 404 when you cannot see it). */
export function useUnlinkIncident(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (incidentId: string) =>
      call(
        api.DELETE('/api/v1/problems/{record_id}/incidents/{incident_id}', {
          params: { path: { record_id: id, incident_id: incidentId } },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: problemKeys.detail(id) });
    },
  });
}

/** Link another problem as related (both sides show it), or remove such a link. */
export function useRelatedProblem(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: async (
      change: { add: string } | { remove: string; version: number },
    ): Promise<unknown> => {
      if ('add' in change) {
        return call(
          api.POST('/api/v1/problems/{record_id}/links', {
            params: {
              path: { record_id: id },
              header: { 'Idempotency-Key': crypto.randomUUID() },
            },
            body: { other_id: change.add },
          }),
        );
      }
      return call(
        api.DELETE('/api/v1/problems/{record_id}/links/{link_id}', {
          params: {
            path: { record_id: id, link_id: change.remove },
            header: ifMatch(change.version),
          },
        }),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: problemKeys.links(id) });
    },
  });
}

/** Merge this problem into another (REQ-PRB-046), or undo the merge; both need If-Match. */
export function useMergeProblem(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (change: { into: string; version: number } | { undo: true; version: number }) =>
      'into' in change
        ? call(
            api.POST('/api/v1/problems/{record_id}/merge', {
              params: { path: { record_id: id }, header: ifMatch(change.version) },
              body: { into_id: change.into },
            }),
          )
        : call(
            api.POST('/api/v1/problems/{record_id}/undo-merge', {
              params: { path: { record_id: id }, header: ifMatch(change.version) },
            }),
          ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: problemKeys.all });
    },
  });
}

export type KnownError = components['schemas']['KnownErrorOut'];

export const knownErrorKeys = {
  all: ['problems', 'known-errors'] as const,
  search: (q: string, retired: boolean) => ['problems', 'known-errors', q, retired] as const,
  suggestions: (incidentId: string) => ['problems', 'known-errors', 'for', incidentId] as const,
};

/** The known error database you may see (REQ-PRB-037), searched in symptoms and workaround. */
export function useKnownErrors(q: string, includeRetired: boolean) {
  return useQuery({
    queryKey: knownErrorKeys.search(q, includeRetired),
    queryFn: () =>
      call(
        api.GET('/api/v1/problems/known-errors', {
          params: { query: { q, include_retired: includeRetired } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

/** Open known errors matching an incident's words (REQ-PRB-038). */
export function useKnownErrorSuggestions(incidentId: string, enabled = true) {
  return useQuery({
    queryKey: knownErrorKeys.suggestions(incidentId),
    queryFn: () =>
      call(
        api.GET('/api/v1/problems/known-errors/suggestions', {
          params: { query: { incident_id: incidentId } },
        }),
      ),
    enabled: enabled && incidentId !== '',
  });
}

/** Mark it a known error (with a comment) or remove the flag (with a reason); If-Match. */
export function useKnownErrorFlag(id: string) {
  const saved = useSavedProblem();
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (
      change:
        | { mark: true; comment: string; version: number }
        | { remove: true; reason: string; version: number },
    ) =>
      'mark' in change
        ? call(
            api.POST('/api/v1/problems/{record_id}/known-error', {
              params: { path: { record_id: id }, header: ifMatch(change.version) },
              body: { comment: change.comment.trim() === '' ? null : change.comment.trim() },
            }),
          )
        : call(
            api.POST('/api/v1/problems/{record_id}/known-error/remove', {
              params: { path: { record_id: id }, header: ifMatch(change.version) },
              body: { reason: change.reason.trim() },
            }),
          ),
    onSuccess: (record) => {
      saved(record);
      void queryClient.invalidateQueries({ queryKey: knownErrorKeys.all });
    },
  });
}

/** Apply a known error to an incident: caused by that problem (REQ-PRB-038 AC2). */
export function useApplyKnownError(incidentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (problemId: string) =>
      call(
        api.POST('/api/v1/problems/{record_id}/incidents', {
          params: { path: { record_id: problemId } },
          body: { incident_id: incidentId, move: false },
        }),
      ),
    onSuccess: (_, problemId) => {
      void queryClient.invalidateQueries({ queryKey: problemKeys.links(problemId) });
      void queryClient.invalidateQueries({ queryKey: knownErrorKeys.all });
    },
  });
}

export type ProblemApprovalPurpose = components['schemas']['ApprovalPurpose'];

/** A problem's approvals (WP-044b s4): its approvers decide; the first decision decides. */
export function useProblemApprovals(id: string) {
  return useQuery({
    queryKey: [...problemKeys.detail(id), 'approvals'] as const,
    queryFn: () =>
      call(
        api.GET('/api/v1/problems/{record_id}/approvals', { params: { path: { record_id: id } } }),
      ),
    enabled: id !== '',
  });
}

/** Ask named people to approve (If-Match on the problem's version). */
export function useRequestProblemApproval(id: string) {
  const saved = useSavedProblem();
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      approverIds,
      purpose,
      version,
    }: {
      approverIds: string[];
      purpose: ProblemApprovalPurpose;
      version: number;
    }) =>
      call(
        api.POST('/api/v1/problems/{record_id}/approvals', {
          params: { path: { record_id: id }, header: ifMatch(version) },
          body: { approver_ids: approverIds, purpose },
        }),
      ),
    onSuccess: (record) => {
      saved(record);
      void queryClient.invalidateQueries({ queryKey: [...problemKeys.detail(id), 'approvals'] });
    },
  });
}

/** Approve or reject one of the problem's approvals (If-Match on the approval's version). */
export function useDecideProblemApproval(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      approvalId,
      version,
      decision,
      comment,
      isPrivate,
    }: {
      approvalId: string;
      version: number;
      decision: 'approve' | 'reject';
      comment: string;
      isPrivate: boolean;
    }) =>
      call(
        api.POST('/api/v1/problems/{record_id}/approvals/{approval_id}/decision', {
          params: {
            path: { record_id: id, approval_id: approvalId },
            header: ifMatch(version),
          },
          body: { decision, comment: comment.trim() === '' ? null : comment, private: isPrivate },
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: problemKeys.detail(id) });
    },
  });
}

/** One message to every requester of the linked incidents, through each incident (REQ-PRB-052). */
export function useMessageIncidentRequesters(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (body: string) =>
      call(
        api.POST('/api/v1/problems/{record_id}/messages/incident-requesters', {
          params: { path: { record_id: id } },
          body: { body },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: problemKeys.detail(id) });
    },
  });
}

export type ProblemFollowUpCopy = components['schemas']['CopyPart'];

/** The open linked incidents a follow-up can resolve, and the texts the problem has. */
export function useProblemFollowUp(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...problemKeys.detail(id), 'follow-up'] as const,
    queryFn: () =>
      call(
        api.GET('/api/v1/problems/{record_id}/follow-up', { params: { path: { record_id: id } } }),
      ),
    enabled: enabled && id !== '',
  });
}

/** Resolve the chosen linked incidents through their own bulk job (REQ-PRB-055). */
export function useStartFollowUp(id: string) {
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ incidentIds, copy }: { incidentIds: string[]; copy: ProblemFollowUpCopy }) =>
      call(
        api.POST('/api/v1/problems/{record_id}/follow-up', {
          params: { path: { record_id: id } },
          body: { incident_ids: incidentIds, copy_text: copy },
        }),
      ),
  });
}

/** The problem category tree (the engine's categories route for problems). */
export function useProblemCategories(enabled = true) {
  return useQuery({
    queryKey: [...problemKeys.all, 'categories'] as const,
    queryFn: () => call(api.GET('/api/v1/problems/categories')),
    enabled,
  });
}

// --- repeated incidents (WP-044c D16, REQ-PRB-068) ---------------------------------------------

export type RepeatHit = components['schemas']['RepeatHitOut'];
export type RepeatHitIncident = components['schemas']['RepeatHitIncidentOut'];

/** The open sets of repeated incidents (for who may create problems; empty otherwise). */
export function useRepeatHits(enabled = true) {
  return useQuery({
    queryKey: problemKeys.repeats,
    queryFn: () => call(api.GET('/api/v1/problem-repeats/hits')),
    enabled,
  });
}

/** A set's incidents you may see (the newest 100). */
export function useRepeatHitIncidents(hitId: string | null) {
  return useQuery({
    queryKey: problemKeys.repeatIncidents(hitId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/problem-repeats/hits/{hit_id}/incidents', {
          params: { path: { hit_id: hitId ?? '' } },
        }),
      ),
    enabled: hitId !== null,
  });
}

export interface RepeatHandle {
  hitId: string;
  version: number;
  outcome: 'problem_created' | 'dismissed';
  problemId?: string;
}

/** A problem was made from the set, or it is dismissed: it leaves the list. */
export function useHandleRepeatHit() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ hitId, version, outcome, problemId }: RepeatHandle) =>
      call(
        api.POST('/api/v1/problem-repeats/hits/{hit_id}/handle', {
          params: { path: { hit_id: hitId }, header: ifMatch(version) },
          body: { outcome, problem_id: problemId ?? null },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: problemKeys.repeats });
    },
  });
}
