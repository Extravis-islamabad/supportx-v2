import type { Edge, Node } from '@xyflow/react';

import type { FlowDefinition, FlowLinkDef, FlowNodeDef } from './definition';

// The definition as React Flow draws it, and back (REQ-WF-008 AC3: a saved definition re-opens
// to the same diagram). Positions are stored left to right; in RTL the canvas shows them
// mirrored (x → -x), so a workflow drawn in English reads the same way round in Arabic.

/** What a drawn node carries: its type, config and the outputs it offers. */
export interface WorkflowNodeData extends Record<string, unknown> {
  nodeType: string;
  config: Record<string, unknown>;
  /** The node's outputs (links leave by these), from the server's node registry. */
  ports: string[];
  /** How many problems the last save found on it (the canvas marks it). */
  problems?: number;
  /** In an execution or test view: the node a run is at, or one it has passed. */
  state?: 'current' | 'passed';
}

export type WorkflowNode = Node<WorkflowNodeData, 'workflow'>;
export type WorkflowEdge = Edge<{ port: string }>;

/** The one input handle every node but the start has. */
export const INPUT = 'in';

export interface GraphOptions {
  /** A node's outputs for its type and config. */
  ports: (node: FlowNodeDef) => string[];
  rtl: boolean;
}

export const linkId = (link: FlowLinkDef): string => `${link.from}:${link.port}->${link.to}`;

const mirror = (x: number, rtl: boolean): number => (rtl && x !== 0 ? -x : x);

export function toGraph(
  definition: FlowDefinition,
  { ports, rtl }: GraphOptions,
): { nodes: WorkflowNode[]; edges: WorkflowEdge[] } {
  return {
    nodes: definition.nodes.map((n) => ({
      id: n.id,
      type: 'workflow',
      position: { x: mirror(n.position.x, rtl), y: n.position.y },
      data: { nodeType: n.type, config: n.config, ports: ports(n) },
    })),
    edges: definition.links.map((l) => ({
      id: linkId(l),
      source: l.from,
      sourceHandle: l.port,
      target: l.to,
      targetHandle: INPUT,
      data: { port: l.port },
    })),
  };
}

/** The definition from what is on the canvas; everything else (format, variables) is kept. */
export function fromGraph(
  definition: FlowDefinition,
  nodes: readonly WorkflowNode[],
  edges: readonly WorkflowEdge[],
  { rtl }: Pick<GraphOptions, 'rtl'>,
): FlowDefinition {
  return {
    ...definition,
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.data.nodeType,
      config: n.data.config,
      position: { x: mirror(Math.round(n.position.x), rtl), y: Math.round(n.position.y) },
    })),
    links: edges.map((e) => ({
      from: e.source,
      port: e.data?.port ?? e.sourceHandle ?? '',
      to: e.target,
    })),
  };
}
