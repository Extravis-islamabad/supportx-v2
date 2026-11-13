// Form rules in the browser (WP-046a S5b; REQ-INC-037): the twin of the server's
// backend/app/modules/work_items/domain/form_rules.py. Both run the shared vectors in
// docs/architecture/form-rule-vectors.json and must give the same answer (AC3), so every rule of
// meaning here is the server's: read that module's docstring before changing anything.
// The browser gives instant feedback only; the server enforces the same rules on save.

export type RuleOp = 'eq' | 'ne' | 'in' | 'not_in' | 'is_null' | 'is_not_null';
export type RuleActionKind = 'show' | 'hide' | 'require' | 'lock' | 'set';
export type RuleScalar = string | number | boolean;

export interface RuleLeaf {
  field: string;
  op: RuleOp;
  value?: RuleScalar | RuleScalar[];
}
export type RuleCondition = RuleLeaf | { and: RuleCondition[] } | { or: RuleCondition[] };

export interface RuleAction {
  do: RuleActionKind;
  field: string;
  /** `set` only: the value an empty field takes. */
  value?: RuleScalar | null;
  /** `hide` only: keep the value instead of clearing it on save. */
  keep_value?: boolean | null;
}

export interface FormRule {
  id: string;
  when: RuleCondition;
  then: RuleAction[];
}

/**
 * A template's stored rules as the evaluator takes them. The API types `when` as any JSON (a
 * nested condition has no closed schema); the server checked its shape when it was saved.
 */
export function asFormRules(
  raw: readonly { id: string; when: unknown; then: RuleAction[] }[],
): FormRule[] {
  return raw.map((r) => ({ id: r.id, when: r.when as RuleCondition, then: r.then }));
}

export interface RuledField {
  shown: boolean;
  required: boolean;
  locked: boolean;
  keep_value: boolean;
}

export interface RuledForm {
  fields: Record<string, RuledField>;
  set_values: Record<string, unknown>;
  matched: string[];
}

/** No value: missing, blank text or an empty list. */
export function isEmptyValue(value: unknown): boolean {
  return (
    value === null ||
    value === undefined ||
    value === '' ||
    (Array.isArray(value) && value.length === 0)
  );
}

const isUuid = (text: string): boolean => text.length === 36 && text.split('-').length === 5;

function asText(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  const text = String(value);
  return isUuid(text) ? text.toLowerCase() : text;
}

function leaf(op: RuleOp, wanted: RuleLeaf['value'], actual: unknown): boolean {
  if (op === 'is_null') return isEmptyValue(actual);
  if (op === 'is_not_null') return !isEmptyValue(actual);
  const listed = op === 'in' || op === 'not_in';
  const choices = new Set((listed ? (wanted as RuleScalar[]) : [wanted as RuleScalar]).map(asText));
  if (isEmptyValue(actual)) return op === 'ne' || op === 'not_in';
  const have = (Array.isArray(actual) ? actual : [actual]).map(asText);
  const overlap = have.some((v) => choices.has(v));
  return op === 'eq' || op === 'in' ? overlap : !overlap;
}

/** Whether a condition holds for these form values. */
export function ruleMatches(condition: RuleCondition, values: Record<string, unknown>): boolean {
  if ('and' in condition) return condition.and.every((c) => ruleMatches(c, values));
  if ('or' in condition) return condition.or.some((c) => ruleMatches(c, values));
  return leaf(condition.op, condition.value, values[condition.field]);
}

/**
 * The form's fields after the rules: one pass, in rule order, over the values as typed (a value
 * a rule sets triggers no other rule); a later rule wins for the same field.
 * `base` is each field's [shown, required] from the template's own field settings.
 */
export function evaluateRules(
  rules: readonly FormRule[],
  base: Readonly<Record<string, readonly [boolean, boolean]>>,
  values: Record<string, unknown>,
): RuledForm {
  const shown = new Map<string, boolean>();
  const required = new Map<string, boolean>();
  for (const [name, [s, r]] of Object.entries(base)) {
    shown.set(name, s);
    required.set(name, r);
  }
  const locked = new Set<string>();
  const keep = new Set<string>();
  const setValues: Record<string, unknown> = {};
  const matched: string[] = [];
  for (const rule of rules) {
    if (!ruleMatches(rule.when, values)) continue;
    matched.push(rule.id);
    for (const action of rule.then) {
      const name = action.field;
      switch (action.do) {
        case 'show':
          shown.set(name, true);
          keep.delete(name);
          break;
        case 'hide':
          shown.set(name, false);
          if (action.keep_value === true) keep.add(name);
          else keep.delete(name);
          break;
        case 'require':
          required.set(name, true);
          break;
        case 'lock':
          locked.add(name);
          break;
        case 'set':
          if (isEmptyValue(values[name])) setValues[name] = action.value;
          break;
      }
    }
  }
  const names = new Set([...shown.keys(), ...required.keys(), ...locked]);
  const fields: Record<string, RuledField> = {};
  for (const name of [...names].sort()) {
    const isShown = shown.get(name) ?? true;
    fields[name] = {
      shown: isShown,
      // A hidden field is never required: nobody could fill it in.
      required: (required.get(name) ?? false) && isShown,
      locked: locked.has(name),
      keep_value: keep.has(name),
    };
  }
  return { fields, set_values: setValues, matched };
}
