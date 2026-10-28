import { useListFormat } from '@supportx/labels';
import { useLabel } from '@supportx/ui';

type People = Record<string, { display_name: string; email: string } | undefined>;

/** History entry kinds the save path writes (rules, routing, assignment, the matrix). */
export const SAVE_PATH_KINDS = new Set(['business_rule', 'routing', 'auto_assign', 'matrix']);

/**
 * Which automation made a change, and why (REQ-WI-004, WP-029): never a bare "automatic". Shared
 * by the History tab and the record's Automation tab (QA WP-029 C3).
 */
export function useAutomationWhy(): (
  automation: Record<string, unknown>,
  people: People,
) => string {
  const t = useLabel();
  const listFormat = useListFormat();
  return (automation, people) => {
    const text = (value: unknown) => (typeof value === 'string' ? value : '');
    switch (automation.kind) {
      case 'business_rule':
        return t('automation.why.rule', { name: text(automation.rule) });
      case 'routing':
        if (automation.reason === 'rule') {
          return t('automation.why.routing_rule', { name: text(automation.rule) });
        }
        return t(
          automation.reason === 'category'
            ? 'automation.why.routing_category'
            : 'automation.why.routing_fallback',
        );
      case 'auto_assign': {
        const method = t(`assign_method.${text(automation.method)}`);
        const loads = automation.loads as Record<string, number> | undefined;
        if (loads === undefined) return t('automation.why.assigned', { method });
        const compared = listFormat(
          Object.entries(loads).map(
            ([user, load]) =>
              `${people[user]?.display_name ?? t('automation.someone')} ${String(load)}`,
          ),
        );
        return t('automation.why.assigned_loads', { method, loads: compared });
      }
      case 'matrix':
        return t('automation.why.matrix');
      case 'auto_move':
        return autoMove(t, text(automation.rule), text(automation.action));
      default:
        return '';
    }
  };
}

/**
 * A status move the system made (WP-020f): the requester replied, confirmed or rejected the fix,
 * nobody answered (auto-close), or the incident was assigned (REQ-INC-051, 096, 098).
 */
function autoMove(t: ReturnType<typeof useLabel>, rule: string, action: string): string {
  switch (rule) {
    case 'requester_reply':
      return t(
        action === 'reopen'
          ? 'automation.why.requester_reply_reopened'
          : 'automation.why.requester_reply_resumed',
      );
    case 'requester_confirmed':
      return t('automation.why.requester_confirmed');
    case 'requester_rejected':
      return t('automation.why.requester_rejected');
    case 'auto_close':
      return t('automation.why.auto_closed');
    case 'assignment':
      return t('automation.why.assignment_move');
    default:
      return '';
  }
}
