import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

// Fine-grained access to assets and CIs (ADR-053): what a rule may name, one role's rules, how
// one person sees them. Every decision is the server's; these only read and send.

export type ResourceCriteria = components['schemas']['ResourceCriteriaOut'];
export type ResourceRule = components['schemas']['ResourceRuleOut'];
export type AccessResource = components['schemas']['ResourceRuleOut']['resource'];
export type PersonResourceAccess = components['schemas']['PersonResourceAccessOut'];

export const resourceAccessKeys = {
  all: [...queryKeys.access.all, 'resource-access'] as const,
  criteria: [...queryKeys.access.all, 'resource-access', 'criteria'] as const,
  rules: (roleId: string) => [...queryKeys.access.all, 'resource-access', 'rules', roleId] as const,
  person: (userId: string) =>
    [...queryKeys.access.all, 'resource-access', 'person', userId] as const,
};

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** GET /resource-access/criteria: per resource, what its rules may name. */
export function useResourceCriteria(enabled = true) {
  return useQuery({
    queryKey: resourceAccessKeys.criteria,
    queryFn: () => call(api.GET('/api/v1/resource-access/criteria')),
    enabled,
  });
}

/** GET /resource-access/rules?role_id=: one role's live rules. */
export function useResourceRules(roleId: string | undefined) {
  return useQuery({
    queryKey: resourceAccessKeys.rules(roleId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/resource-access/rules', {
          params: { query: { role_id: roleId ?? '' } },
        }),
      ),
    enabled: roleId !== undefined,
  });
}

/** GET /people/{id}/access-rules: how one person sees assets and CIs (their own compile). */
export function usePersonResourceAccess(userId: string | undefined) {
  return useQuery({
    queryKey: resourceAccessKeys.person(userId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/people/{user_id}/access-rules', {
          params: { path: { user_id: userId ?? '' } },
        }),
      ),
    enabled: userId !== undefined,
  });
}

/**
 * Add, change or remove one role's rule. A new rule takes an Idempotency-Key (one per attempt,
 * the same on a retry); a change or removal sends the version read. Errors are the screen's.
 */
export function useSaveResourceRule(roleId: string) {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: resourceAccessKeys.all });
  };
  return useMutation({
    meta: { silent: true },
    mutationFn: async ({
      resource,
      criteria,
      current,
      key,
    }: {
      resource: AccessResource;
      /** The new criteria, or null to remove the rule. */
      criteria: Record<string, unknown> | null;
      current: ResourceRule | undefined;
      key: string;
    }) => {
      if (current === undefined) {
        if (criteria === null) return null;
        return call(
          api.POST('/api/v1/resource-access/rules', {
            params: { header: { 'Idempotency-Key': key } },
            body: { role_id: roleId, resource, criteria },
          }),
        );
      }
      if (criteria === null) {
        await call(
          api.DELETE('/api/v1/resource-access/rules/{rule_id}', {
            params: { path: { rule_id: current.id }, header: ifMatch(current.version) },
          }),
        );
        return null;
      }
      return call(
        api.PATCH('/api/v1/resource-access/rules/{rule_id}', {
          params: { path: { rule_id: current.id }, header: ifMatch(current.version) },
          body: { criteria },
        }),
      );
    },
    onSuccess: refresh,
    // A stale rule: fetch the saved ones, so the list shows what is there now.
    onError: (error) => {
      if (error instanceof ApiError && error.isConflict) refresh();
    },
  });
}
