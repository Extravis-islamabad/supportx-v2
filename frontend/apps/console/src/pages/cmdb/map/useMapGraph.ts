import { useQueries, useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';

import {
  neighbours,
  queryKeys,
  type CiGraph,
  type CiMapEdge,
  type CiMapNode,
  type NeighboursQuery,
} from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';

/**
 * A node on the map. `key` is the CI's ID for a CI the reader may open. A restricted placeholder's
 * key is only unique within one answer (`r1`…), so it is prefixed with the CI whose neighbours
 * found it: two answers' `r1` are two different placeholders (lane C's condition 2).
 */
export interface ShownNode {
  key: string;
  node: CiMapNode;
}

export interface ShownEdge {
  key: string;
  edge: CiMapEdge;
  from: string;
  to: string;
}

export interface MapGraph {
  nodes: ShownNode[];
  edges: ShownEdge[];
  /** An answer had more nodes than it could carry: the map says so in words (condition 10). */
  truncated: boolean;
  nodeMax: number;
  countsAvailable: boolean;
  loading: boolean;
  error: unknown;
}

/** The node set's IDs a live message is matched against, at most this many (condition 9). */
export const LIVE_NODE_CAP = 1000;

/** Merge the base's answer and each expanded node's answer into one map. */
export function mergeGraphs(answers: readonly { from: string; graph: CiGraph }[]): MapGraph {
  const nodes = new Map<string, ShownNode>();
  const edges = new Map<string, ShownEdge>();
  let truncated = false;
  let nodeMax = 500;
  let countsAvailable = false;
  for (const { from, graph } of answers) {
    truncated ||= graph.truncated;
    nodeMax = graph.node_max;
    countsAvailable ||= graph.counts_available;
    const keyOf = new Map<string, string>();
    for (const node of graph.nodes) {
      const key = node.restricted ? `${from}~${node.key}` : node.key;
      keyOf.set(node.key, key);
      // The first answer that showed a CI keeps it; a later one only adds what is missing.
      if (!nodes.has(key)) nodes.set(key, { key, node });
    }
    for (const edge of graph.edges) {
      const a = keyOf.get(edge.from_key);
      const b = keyOf.get(edge.to_key);
      if (a === undefined || b === undefined) continue;
      const key = edge.id ?? `${a}>${b}:${edge.type_id}`;
      if (!edges.has(key)) edges.set(key, { key, edge, from: a, to: b });
    }
  }
  return {
    nodes: [...nodes.values()],
    edges: [...edges.values()],
    truncated,
    nodeMax,
    countsAvailable,
    loading: false,
    error: null,
  };
}

/**
 * The map of `base` with the nodes in `expanded` opened one step further (AC1), each answer
 * cached on its own. Live (condition 9): one list channel for the CMDB, its messages matched
 * against the map's node set (capped), never a channel per node; a change on a shown CI
 * refetches the answers it may be in (§8.3: the reconcile, never a patched guess).
 */
export function useMapGraph(
  base: string,
  expanded: readonly string[],
  query: NeighboursQuery,
  enabled = true,
): MapGraph {
  const queryClient = useQueryClient();
  const sources = useMemo(() => [base, ...expanded.filter((k) => k !== base)], [base, expanded]);
  const answers = useQueries({
    queries: sources.map((id, i) => ({
      queryKey: queryKeys.cmdb.neighbours(id, i === 0 ? query : { ...query, depth: 1 }),
      queryFn: () => neighbours(id, i === 0 ? query : { ...query, depth: 1 }),
      enabled,
      retry: false,
    })),
    // A stable function: TanStack Query shares the combined result while nothing changed, so
    // the map is merged (and laid out) again only when an answer did.
    combine: combined,
  });
  const graph = useMemo(
    () =>
      mergeGraphs(
        sources.flatMap((from, i) => {
          const answer = answers.data[i];
          return answer === undefined ? [] : [{ from, graph: answer }];
        }),
      ),
    [sources, answers.data],
  );
  const ids = useMemo(
    () =>
      new Set(
        graph.nodes
          .filter((n) => !n.node.restricted)
          .slice(0, LIVE_NODE_CAP)
          .map((n) => n.key),
      ),
    [graph.nodes],
  );
  useListChannel(
    enabled ? 'cmdb' : null,
    (message) => {
      if (message.covered === true) return; // a refresh: `covers` refetched every source
      if (!message.ids.some((id) => ids.has(id))) return;
      for (const id of sources) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.neighboursOf(id) });
      }
    },
    { covers: sources.map((id) => queryKeys.cmdb.neighboursOf(id)) },
  );
  return { ...graph, loading: answers.pending && enabled, error: answers.error };
}

function combined(results: readonly { data?: CiGraph; isPending: boolean; error: unknown }[]) {
  return {
    data: results.map((r) => r.data),
    pending: results[0]?.isPending === true,
    error: results[0]?.error ?? null,
  };
}
