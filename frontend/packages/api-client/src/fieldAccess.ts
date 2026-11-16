import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

// Field access per role (ADR-047): the rule-able fields, one role's rules, who sees a field how.
// Every decision is the server's; these only read and send (roles.view / roles.manage).

export type RuleableField = components['schemas']['RuleableFieldOut'];
export type FieldCatalogue = components['schemas']['CatalogueOut'];
export type FieldAccessRule = components['schemas']['FieldRuleOut'];
export type FieldMode = components['schemas']['FieldRuleOut']['mode'];
export type EffectiveFieldAccess = components['schemas']['EffectiveOut'];

/** The modes a rule may set, from the clearest to the most withheld. */
export const FIELD_RULE_MODES = ['read_only', 'masked', 'hidden'] as const;

export const fieldAccessKeys = {
  all: [...queryKeys.access.all, 'field-access'] as const,
  catalogue: [...queryKeys.access.all, 'field-access', 'catalogue'] as const,
  rules: (roleId: string) => [...queryKeys.access.all, 'field-access', 'rules', roleId] as const,
  effective: (recordType: string, field: string) =>
    [...queryKeys.access.all, 'field-access', 'effective', recordType, field] as const,
};

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** GET /field-access/catalogue: every record type's rule-able fields. */
export function useFieldCatalogue(enabled = true) {
  return useQuery({
    queryKey: fieldAccessKeys.catalogue,
    queryFn: () => call(api.GET('/api/v1/field-access/catalogue')),
    enabled,
  });
}

/** GET /field-access/rules?role_id=: one role's live rules. */
export function useFieldRules(roleId: string | undefined) {
  return useQuery({
    queryKey: fieldAccessKeys.rules(roleId ?? ''),
    queryFn: () =>
      call(api.GET('/api/v1/field-access/rules', { params: { query: { role_id: roleId ?? '' } } })),
    enabled: roleId !== undefined,
  });
}

/** GET /field-access/effective: who sees one field how (the clearest of their roles wins). */
export function useEffectiveFieldAccess(recordType: string, field: string | undefined) {
  return useQuery({
    queryKey: fieldAccessKeys.effective(recordType, field ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/field-access/effective', {
          params: { query: { record_type: recordType, field: field ?? '' } },
        }),
      ),
    enabled: field !== undefined,
  });
}

/**
 * Set one field's mode for a role: a new rule, another mode, or no rule. Each change saves at
 * once (the tab has no footer Save: lane C's slice c review). Errors are the screen's to show.
 */
export function useSetFieldRule(roleId: string) {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: fieldAccessKeys.all });
  };
  return useMutation({
    meta: { silent: true },
    mutationFn: async ({
      recordType,
      field,
      mode,
      current,
      key,
    }: {
      recordType: string;
      field: string;
      /** The new mode, or null for no rule. */
      mode: FieldMode | null;
      /** The rule now in place, if any (its version goes as If-Match). */
      current: FieldAccessRule | undefined;
      /** The Idempotency-Key of a new rule (one per attempt, the same on a retry). */
      key: string;
    }) => {
      if (current === undefined) {
        if (mode === null) return null;
        return call(
          api.POST('/api/v1/field-access/rules', {
            params: { header: { 'Idempotency-Key': key } },
            body: { role_id: roleId, record_type: recordType, field, mode },
          }),
        );
      }
      if (mode === null) {
        await call(
          api.DELETE('/api/v1/field-access/rules/{rule_id}', {
            params: { path: { rule_id: current.id }, header: ifMatch(current.version) },
          }),
        );
        return null;
      }
      return call(
        api.PATCH('/api/v1/field-access/rules/{rule_id}', {
          params: { path: { rule_id: current.id }, header: ifMatch(current.version) },
          body: { mode },
        }),
      );
    },
    onSuccess: refresh,
    // A stale rule: fetch the saved ones, so the row shows what is there now.
    onError: (error) => {
      if (error instanceof ApiError && error.isConflict) refresh();
    },
  });
}
