import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
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
  const options = { meta: { silent: true }, onSuccess: refresh };
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

/** Set yourself (or, with users.manage, someone else) Available or Away. */
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
