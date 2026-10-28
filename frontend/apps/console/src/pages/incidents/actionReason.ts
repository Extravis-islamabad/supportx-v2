import type { Incident } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

type ActionState = Incident['actions'][number];

/**
 * Why an action is disabled, in words. "Only certain people" names them: roles, groups and the
 * people on the record the admin limited it to (QA WP-029 C2).
 */
export function useActionReason(): (state: Pick<ActionState, 'reason' | 'allowed_for'>) => string {
  const t = useLabel();
  return (state) => {
    const who = state.allowed_for;
    if (state.reason !== 'not_for_you' || who == null)
      return t(`action_reason.${state.reason ?? ''}`);
    const names = [
      ...who.roles.map((role) => (role.system ? t(`role.${role.key}`) : role.name)),
      ...who.groups.map((group) => t('action_reason.group_members', { group })),
      ...who.relatives.map((relative) => t(`action_reason.relative.${relative}`)),
    ];
    if (names.length === 0) return t('action_reason.not_for_you');
    return t('action_reason.not_for_you_who', { who: names.join(t('list.separator')) });
  };
}
