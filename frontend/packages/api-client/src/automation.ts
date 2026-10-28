import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

export type RuleOut = components['schemas']['RuleOut'];
export type RuleIn = components['schemas']['RuleIn'];
export type RulePatch = components['schemas']['RulePatch'];
export type RuleActionIO = components['schemas']['RuleActionIO'];
export type RuleFieldOut = components['schemas']['RuleFieldOut'];
export type RoutingOut = components['schemas']['RoutingOut'];
export type RoutingIn = components['schemas']['RoutingIn'];
export type RoutingPatch = components['schemas']['RoutingPatch'];
export type RoutingSettingsOut = components['schemas']['RoutingSettingsOut'];
export type AssignmentSettingsOut = components['schemas']['AssignmentSettingsOut'];
export type AssignmentSettingsIn = components['schemas']['AssignmentSettingsIn'];
export type AvailabilityState = components['schemas']['AvailabilityOut']['state'];
export type TriggerOut = components['schemas']['TriggerOut'];
export type TriggerIn = components['schemas']['TriggerIn'];
export type TriggerPatch = components['schemas']['TriggerPatch'];
export type TriggerActionIO = components['schemas']['TriggerActionIO'];
export type TransitionOut = components['schemas']['TransitionSettingsOut'];
export type TransitionIn = components['schemas']['TransitionSettingsIn'];
export type LoopStopOut = components['schemas']['LoopStopOut'];
export type AutomationRunOut = components['schemas']['AutomationRunOut'];

function ifMatch(version: number) {
  return { 'If-Match': `"${String(version)}"` };
}

/** The fields business rules may use for a record type (the editor builds itself from them). */
export function useRuleFields(recordType: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.automation.fields(recordType),
    queryFn: () =>
      call(
        api.GET('/api/v1/automation/fields', { params: { query: { record_type: recordType } } }),
      ),
    enabled,
  });
}

/** A record type's business rules, in order (drafts and disabled ones included). */
export function useBusinessRules(recordType: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.automation.rules(recordType),
    queryFn: () =>
      call(api.GET('/api/v1/automation/rules', { params: { query: { record_type: recordType } } })),
    enabled,
  });
}

/** A record type's routing rules, in order. */
export function useRoutingRules(recordType: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.automation.routing(recordType),
    queryFn: () =>
      call(
        api.GET('/api/v1/automation/routing', { params: { query: { record_type: recordType } } }),
      ),
    enabled,
  });
}

/** Fallback group and the category suggestion switch. */
export function useRoutingSettings(recordType: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.automation.routingSettings(recordType),
    queryFn: () =>
      call(
        api.GET('/api/v1/automation/routing-settings', {
          params: { query: { record_type: recordType } },
        }),
      ),
    enabled,
  });
}

/**
 * Add, change, remove and order business rules and routing rules. Each change carries the
 * version the editor opened (If-Match); the editor shows problems at their fields and the
 * conflict dialog itself, so no global toast.
 */
export function useAutomationChange() {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.automation.all });
  };
  const options = {
    meta: { silent: true },
    onSuccess: refresh,
    // A stale save: fetch the saved version, so the conflict dialog can compare (QA WP-029 BUG-05).
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.isConflict) refresh();
    },
  };
  return {
    createRule: useMutation({
      ...options,
      mutationFn: (body: RuleIn) => call(api.POST('/api/v1/automation/rules', { body })),
    }),
    updateRule: useMutation({
      ...options,
      mutationFn: ({ id, version, body }: { id: string; version: number; body: RulePatch }) =>
        call(
          api.PATCH('/api/v1/automation/rules/{rule_id}', {
            params: { path: { rule_id: id }, header: ifMatch(version) },
            body,
          }),
        ),
    }),
    deleteRule: useMutation({
      ...options,
      mutationFn: ({ id, version }: { id: string; version: number }) =>
        call(
          api.DELETE('/api/v1/automation/rules/{rule_id}', {
            params: { path: { rule_id: id }, header: ifMatch(version) },
          }),
        ),
    }),
    orderRules: useMutation({
      ...options,
      mutationFn: (body: { record_type: string; ids: string[] }) =>
        call(api.PUT('/api/v1/automation/rules-order', { body })),
    }),
    createRouting: useMutation({
      ...options,
      mutationFn: (body: RoutingIn) => call(api.POST('/api/v1/automation/routing', { body })),
    }),
    updateRouting: useMutation({
      ...options,
      mutationFn: ({ id, version, body }: { id: string; version: number; body: RoutingPatch }) =>
        call(
          api.PATCH('/api/v1/automation/routing/{rule_id}', {
            params: { path: { rule_id: id }, header: ifMatch(version) },
            body,
          }),
        ),
    }),
    deleteRouting: useMutation({
      ...options,
      mutationFn: ({ id, version }: { id: string; version: number }) =>
        call(
          api.DELETE('/api/v1/automation/routing/{rule_id}', {
            params: { path: { rule_id: id }, header: ifMatch(version) },
          }),
        ),
    }),
    orderRouting: useMutation({
      ...options,
      mutationFn: (body: { record_type: string; ids: string[] }) =>
        call(api.PUT('/api/v1/automation/routing-order', { body })),
    }),
    createTrigger: useMutation({
      ...options,
      mutationFn: (body: TriggerIn) => call(api.POST('/api/v1/automation/triggers', { body })),
    }),
    updateTrigger: useMutation({
      ...options,
      mutationFn: ({ id, version, body }: { id: string; version: number; body: TriggerPatch }) =>
        call(
          api.PATCH('/api/v1/automation/triggers/{trigger_id}', {
            params: { path: { trigger_id: id }, header: ifMatch(version) },
            body,
          }),
        ),
    }),
    deleteTrigger: useMutation({
      ...options,
      mutationFn: ({ id, version }: { id: string; version: number }) =>
        call(
          api.DELETE('/api/v1/automation/triggers/{trigger_id}', {
            params: { path: { trigger_id: id }, header: ifMatch(version) },
          }),
        ),
    }),
    orderTriggers: useMutation({
      ...options,
      mutationFn: (body: { record_type: string; ids: string[] }) =>
        call(api.PUT('/api/v1/automation/triggers-order', { body })),
    }),
    saveTransition: useMutation({
      ...options,
      mutationFn: ({
        recordType,
        action,
        version,
        body,
      }: {
        recordType: string;
        action: string;
        version: number;
        body: TransitionIn;
      }) =>
        call(
          api.PUT('/api/v1/automation/transitions/{action}', {
            params: {
              path: { action },
              query: { record_type: recordType },
              header: ifMatch(version),
            },
            body,
          }),
        ),
    }),
    resetTransition: useMutation({
      ...options,
      mutationFn: ({
        recordType,
        action,
        version,
      }: {
        recordType: string;
        action: string;
        version: number;
      }) =>
        call(
          api.DELETE('/api/v1/automation/transitions/{action}', {
            params: {
              path: { action },
              query: { record_type: recordType },
              header: ifMatch(version),
            },
          }),
        ),
    }),
    saveRoutingSettings: useMutation({
      ...options,
      mutationFn: ({
        recordType,
        version,
        body,
      }: {
        recordType: string;
        version: number;
        body: { fallback_group_id?: string | null; use_category_group?: boolean };
      }) =>
        call(
          api.PUT('/api/v1/automation/routing-settings', {
            params: { query: { record_type: recordType }, header: ifMatch(version) },
            body,
          }),
        ),
    }),
  };
}

/** A group's auto-assignment set-up (version 0: never set up, off). */
export function useGroupAssignment(groupId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.automation.assignment(groupId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/automation/groups/{group_id}/assignment', {
          params: { path: { group_id: groupId ?? '' } },
        }),
      ),
    enabled: groupId !== undefined,
  });
}

/** Switch a group's auto-assignment on or off and set it up. */
export function useSaveGroupAssignment() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      groupId,
      version,
      body,
    }: {
      groupId: string;
      version: number;
      body: AssignmentSettingsIn;
    }) =>
      call(
        api.PUT('/api/v1/automation/groups/{group_id}/assignment', {
          params: { path: { group_id: groupId }, header: ifMatch(version) },
          body,
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.automation.assignment(saved.group_id), saved);
    },
  });
}

/** Who is available (Away people are never auto-assigned). */
export function useAvailability(userIds: string[], enabled = true) {
  return useQuery({
    queryKey: queryKeys.automation.availability(userIds),
    queryFn: () =>
      call(
        api.GET('/api/v1/automation/availability', { params: { query: { user_ids: userIds } } }),
      ),
    enabled: enabled && userIds.length > 0,
  });
}

/** Who set someone Available or Away, and when: newest first (QA WP-029 follow-up). */
export function useAvailabilityHistory(userId: string, enabled = true) {
  return useQuery({
    queryKey: [...queryKeys.automation.availability([]), 'history', userId] as const,
    queryFn: () =>
      call(
        api.GET('/api/v1/automation/availability/{user_id}/history', {
          params: { path: { user_id: userId } },
        }),
      ),
    enabled,
  });
}

/** Set yourself, a member of a group you lead, or (with users.manage) anyone Available or Away. */
export function useSetAvailability() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, state }: { userId: string; state: AvailabilityState }) =>
      call(
        api.PUT('/api/v1/automation/availability/{user_id}', {
          params: { path: { user_id: userId } },
          body: { state },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: [...queryKeys.automation.all, 'availability'],
      });
    },
  });
}

/** A record type's triggers, in order (drafts and disabled ones included). */
export function useTriggers(recordType: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.automation.triggers(recordType),
    queryFn: () =>
      call(
        api.GET('/api/v1/automation/triggers', { params: { query: { record_type: recordType } } }),
      ),
    enabled,
  });
}

/** Transition settings of a record type (only actions that have some). */
export function useTransitionSettings(recordType: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.automation.transitions(recordType),
    queryFn: () =>
      call(
        api.GET('/api/v1/automation/transitions', {
          params: { query: { record_type: recordType } },
        }),
      ),
    enabled,
  });
}

/** Loops the guard stopped in the last 24 hours (the admins' banner). */
export function useLoopStops(enabled = true) {
  return useQuery({
    queryKey: queryKeys.automation.loopStops,
    queryFn: () => call(api.GET('/api/v1/automation/loop-stops')),
    enabled,
    meta: { silent: true },
  });
}

/** What automation did on an incident: triggers' outcomes and loop stops (live with the record). */
export function useIncidentAutomation(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.automation(id),
    queryFn: () =>
      call(
        api.GET('/api/v1/incidents/{record_id}/automation', {
          params: { path: { record_id: id } },
        }),
      ),
    enabled,
  });
}
