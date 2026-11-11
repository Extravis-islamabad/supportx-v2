import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { useSingleFlight } from './incidents';
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
