import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

// WP-037: the tenant's AI settings (Admin › AI). Every AI feature reads them to know whether it
// may show; a change reaches every screen live (`ai.settings_changed`).

export type AiSettings = components['schemas']['AiSettingsOut'];
export type AiSettingsInput = components['schemas']['AiSettingsPatch'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** A stale change: fetch the saved version, so the conflict dialog can compare. */
function onConflict(refresh: () => void) {
  return (error: unknown) => {
    if (error instanceof ApiError && error.isConflict) refresh();
  };
}

/**
 * The AI switches, the features with their state, and the model. `silent`: for screens that
 * only hide an AI feature when the settings cannot be read (no toast).
 */
export function useAiSettings(enabled = true, silent = false) {
  return useQuery({
    meta: silent ? { silent: true } : undefined,
    queryKey: queryKeys.ai.settings,
    queryFn: () => call(api.GET('/api/v1/ai/settings')),
    enabled,
  });
}

/** Change the AI settings (If-Match); refusals come back by field. */
export function useSaveAiSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, version }: { body: AiSettingsInput; version: number }) =>
      call(api.PATCH('/api/v1/ai/settings', { params: { header: ifMatch(version) }, body })),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.ai.settings, saved);
    },
    onError: onConflict(
      () => void queryClient.invalidateQueries({ queryKey: queryKeys.ai.settings }),
    ),
  });
}

// WP-038: a record's conversation summary (REQ-INC-137). Made on request through the gateway;
// a newer reply or note marks it stale (`ai.summary_changed` on the record channel).

export type AiSummary = components['schemas']['SummaryOut'];
export type SummaryRecordType = 'incident';

/** The record's latest summary at your level, or `summary: null` when none was made yet. */
export function useAiSummary(recordType: SummaryRecordType, id: string, enabled = true) {
  return useQuery({
    meta: { silent: true }, // an optional card: it hides or shows its own state, never a toast
    queryKey: queryKeys.ai.summary(recordType, id),
    queryFn: () =>
      call(
        api.GET('/api/v1/ai/summaries/{record_type}/{record_id}', {
          params: { path: { record_type: recordType, record_id: id } },
        }),
      ),
    enabled: enabled && id !== '',
  });
}

/** Summarise the conversation now; the answer replaces the stored one. */
export function useRefreshAiSummary(recordType: SummaryRecordType, id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      call(
        api.POST('/api/v1/ai/summaries/{record_type}/{record_id}/refresh', {
          params: { path: { record_type: recordType, record_id: id } },
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.ai.summary(recordType, id), saved);
    },
  });
}

// WP-038: writing help in the reply and note editors (REQ-INC-136). The answer goes to a
// review panel only; what the person did with it is recorded (REQ-AI-031).

export type WritingRequest = components['schemas']['WritingIn'];
export type WritingAnswer = components['schemas']['WritingOut'];
export type AiOutcome = 'accepted' | 'edited' | 'discarded';

/** A draft from an instruction, or the person's text improved. */
export function useWritingHelp(recordType: SummaryRecordType, id: string) {
  return useMutation({
    meta: { silent: true }, // the panel shows the refusal or failure itself
    mutationFn: (body: WritingRequest) =>
      call(
        api.POST('/api/v1/ai/writing/{record_type}/{record_id}', {
          params: { path: { record_type: recordType, record_id: id } },
          body,
        }),
      ),
  });
}

/** What the person did with an AI answer: kept, edited or thrown away. */
export function useAiOutcome() {
  return useMutation({
    meta: { silent: true }, // usage reporting only: never in the person's way
    mutationFn: ({ callId, outcome }: { callId: string; outcome: AiOutcome }) =>
      call(
        api.POST('/api/v1/ai/calls/{call_id}/outcome', {
          params: { path: { call_id: callId } },
          body: { outcome },
        }),
      ),
  });
}
