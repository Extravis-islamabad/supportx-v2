import type { CatalogItemInput } from '@supportx/api-client';

export type Approval = NonNullable<CatalogItemInput['approval']>;
export type Stage = NonNullable<Approval['stages']>[number];
export type Approver = NonNullable<Stage['approvers']>[number];
export type Kind = Approver['kind'];
export type Rule = Stage['rule'];
export type AutoRule = NonNullable<Stage['auto_rules']>[number];
export type EscalateTo = Stage['escalate_to'];
// WP-047a S3a (REQ-SR-034, Essentials): where a stage's approval goes after its last reminder.
export const ESCALATE_TO: EscalateTo[] = ['backup', 'approver_manager', 'fulfilment_group', 'none'];

export const MAX_STAGES = 10; // REQ-SR-029 AC4: requests only (staged record types keep 5)
export const MAX_APPROVERS = 10;
export const MAX_AUTO_RULES = 5; // REQ-SR-033, as the server's
export const KINDS: Kind[] = [
  'person',
  'requested_for_manager',
  'manager_of_manager',
  'department_head',
  'group_leads',
  'group',
  'person_answer',
  'asset_owner',
  'ci_owner',
];
// The kinds every edition keeps (today's single stage); the rest are REQ-SR-031, Professional.
export const TODAYS_KINDS: Kind[] = ['person', 'requested_for_manager'];
export const RULES: Rule[] = ['any', 'all', 'majority'];
// The condition operators a stage takes (the form rules' DSL, app/shared/conditions.py).
export const OPS = ['eq', 'ne', 'in', 'not_in', 'is_null', 'is_not_null'] as const;
export type Op = (typeof OPS)[number];

/** A new stage: the requested-for person's manager, decided by the first answer. */
export function blankStage(): Stage {
  return {
    approvers: [{ kind: 'requested_for_manager' }],
    rule: 'any',
    comments_required: false,
    self_approval: false,
    escalate_to: 'backup',
  };
}

/** The single stage an item had before S2a, as the first of a list. */
export function stageOf(approval: Approval): Stage {
  return {
    approvers: approval.approvers,
    rule: approval.rule,
    backup_id: approval.backup_id ?? null,
    comments_required: approval.comments_required,
    self_approval: approval.self_approval,
    parallel_group: approval.parallel_group ?? null,
    condition: approval.condition ?? null,
    auto_earlier: approval.auto_earlier ?? null,
    auto_rules: approval.auto_rules ?? [],
    escalate_to: approval.escalate_to,
  };
}

/** A condition value as text (an answer code, a number or a flag; anything else is blank). */
export function valueText(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
    ? String(value)
    : '';
}
