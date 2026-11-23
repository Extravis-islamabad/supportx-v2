import type { NodeTypeOut } from '@supportx/api-client';

type Translate = (key: string, params?: Record<string, string | number>) => string;

// The palette's groups, in the order they are shown (REQ-WF-028: named in words).
export const CATEGORIES = ['flow', 'logic', 'people', 'actions', 'structure'] as const;

// A node type's group, for the canvas (the palette has it from the server too).
export const CATEGORY_OF: Record<string, NodeTypeOut['category'] | undefined> = {
  start: 'flow',
  end: 'flow',
  set_status: 'flow',
  if: 'logic',
  switch: 'logic',
  wait: 'logic',
  timer: 'logic',
  set_variable: 'logic',
  approval: 'people',
  tasks: 'people',
  notify: 'people',
  field_update: 'actions',
  note: 'actions',
  webhook: 'actions',
  function: 'actions',
  split: 'structure',
  join: 'structure',
  sub_flow: 'structure',
};

// Outputs every node type shares a word for; a switch case or a split branch is named by the
// admin, and shown as typed.
const KNOWN_PORTS = new Set([
  'next',
  'yes',
  'no',
  'default',
  'overtaken',
  'timeout',
  'error',
  'approved',
  'rejected',
]);

/** Whether an output has a word of its own (not a name the admin typed, not an internal code). */
export const isKnownPort = (port: string): boolean => KNOWN_PORTS.has(port);

/** An output's name for people: a known word, or what the admin called it. */
export function portName(t: Translate, _nodeType: string, port: string): string {
  return KNOWN_PORTS.has(port) ? t(`workflow_port.${port}`) : port;
}

/** A node id not yet used: the type's code and the next free number ("notify_2"). */
export function freeId(type: string, taken: ReadonlySet<string>): string {
  for (let n = 1; ; n += 1) {
    const id = n === 1 ? type : `${type}_${String(n)}`;
    if (!taken.has(id)) return id;
  }
}

/** A workflow problem in words: its own label, or the shared conditions grammar's. */
export function problemText(
  t: Translate,
  code: string,
  params: Record<string, unknown> = {},
): string {
  const values = Object.fromEntries(
    Object.entries(params).map(([k, v]) => [k, typeof v === 'number' ? v : String(v)]),
  );
  const own = `workflow_problem.${code}`;
  const shown = t(own, values);
  return shown === own ? t(`errors.field.${code}`, values) : shown;
}

/** The node types with a settings form of their own (NodeForms); the rest use Advanced. */
export const FORM_TYPES = new Set([
  'if',
  'switch',
  'notify',
  'timer',
  'wait',
  'set_status',
  'note',
  'tasks',
  'approval',
  'field_update',
  'webhook',
  'set_variable',
  'split',
  'join',
  'sub_flow',
  'function',
]);
