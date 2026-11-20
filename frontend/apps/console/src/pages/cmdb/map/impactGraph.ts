import type { CiImpact } from '@supportx/api-client';

import type { MapGraph } from './useMapGraph';

/** The answer as a map: each CI joined to the one it was reached from, by the stored link. */
export function impactGraph(impact: CiImpact): MapGraph {
  const nodes = [impact.start, ...impact.cis].map((node) => ({ key: node.key, node }));
  const edges = impact.cis.flatMap((node) => {
    if (node.via == null || node.via_type_id == null) return [];
    const forward = node.via_forward;
    const from = forward ? node.via : node.key;
    const to = forward ? node.key : node.via;
    const key = `${from}>${to}:${node.via_type_id}`;
    return [
      {
        key,
        from,
        to,
        edge: { id: null, type_id: node.via_type_id, from_key: from, to_key: to, version: null },
      },
    ];
  });
  return {
    nodes,
    edges,
    truncated: impact.truncated,
    nodeMax: impact.ci_max,
    countsAvailable: false,
    loading: false,
    error: null,
  };
}
