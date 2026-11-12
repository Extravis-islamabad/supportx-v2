// The stored shape of a workflow definition (ADR-043 §1): data, not code. The API carries it as
// a JSON object (`draft`, `definition`), so its shape is described here once, for the designer;
// the server checks it on every save (domain/workflows.py `parse`).

export interface FlowPosition {
  x: number;
  y: number;
}

export interface FlowNodeDef {
  id: string;
  type: string;
  config: Record<string, unknown>;
  /** Where the node sits, in left-to-right coordinates (mirrored on screen in RTL). */
  position: FlowPosition;
}

export interface FlowLinkDef {
  from: string;
  /** The named output of `from` the link leaves by ("next", "true", "approved", …). */
  port: string;
  to: string;
}

export interface FlowDefinition {
  format: number;
  nodes: FlowNodeDef[];
  links: FlowLinkDef[];
  variables: unknown[];
}

/** What a workflow variable may hold (the server's VARIABLE_KINDS). */
export const VARIABLE_KINDS = ['text', 'number', 'boolean', 'datetime'] as const;
export type VariableKind = (typeof VARIABLE_KINDS)[number];

/** A workflow's own variable: its name and what it holds (ADR-043 §1). */
export interface WorkflowVariable {
  name: string;
  kind: VariableKind;
}

/** The variables of a definition, as the designer edits them; anything unreadable is left out. */
export function readVariables(raw: readonly unknown[]): WorkflowVariable[] {
  return raw.filter(isObject).map((v) => ({
    name: text(v.name),
    kind: (VARIABLE_KINDS as readonly string[]).includes(text(v.kind))
      ? (text(v.kind) as VariableKind)
      : 'text',
  }));
}

/** An empty definition: a start and an end, not yet joined (the server names what is missing). */
export function emptyDefinition(): FlowDefinition {
  return {
    format: 1,
    nodes: [
      { id: 'start', type: 'start', config: {}, position: { x: 0, y: 0 } },
      { id: 'end', type: 'end', config: {}, position: { x: 0, y: 280 } },
    ],
    links: [],
    variables: [],
  };
}

/** A definition from the API's untyped JSON, tolerating missing parts (never trusting it). */
export function readDefinition(raw: unknown): FlowDefinition {
  const source = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>;
  const nodes = Array.isArray(source.nodes) ? source.nodes : [];
  const links = Array.isArray(source.links) ? source.links : [];
  return {
    format: typeof source.format === 'number' ? source.format : 1,
    nodes: nodes.filter(isObject).map((n) => ({
      id: text(n.id),
      type: text(n.type),
      config: isObject(n.config) ? { ...n.config } : {},
      position: readPosition(n.position),
    })),
    links: links.filter(isObject).map((l) => ({
      from: text(l.from),
      port: text(l.port),
      to: text(l.to),
    })),
    variables: Array.isArray(source.variables) ? [...(source.variables as unknown[])] : [],
  };
}

/** A string field, or "" for anything else (an object never becomes "[object Object]"). */
function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readPosition(value: unknown): FlowPosition {
  if (!isObject(value)) return { x: 0, y: 0 };
  const x = typeof value.x === 'number' && Number.isFinite(value.x) ? value.x : 0;
  const y = typeof value.y === 'number' && Number.isFinite(value.y) ? value.y : 0;
  return { x, y };
}
