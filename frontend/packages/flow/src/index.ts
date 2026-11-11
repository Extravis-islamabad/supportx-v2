// @supportx/flow: React Flow parts for workflows, life cycles and CMDB maps (architecture.md §6.7).
// WP-048b S4: the workflow definition, its mapping to the canvas, and the automatic layout.
export {
  emptyDefinition,
  readDefinition,
  type FlowDefinition,
  type FlowLinkDef,
  type FlowNodeDef,
  type FlowPosition,
} from './definition';
export {
  INPUT,
  fromGraph,
  linkId,
  toGraph,
  type GraphOptions,
  type WorkflowEdge,
  type WorkflowNode,
  type WorkflowNodeData,
} from './graph';
export { COLUMN, ROW, layout, withLayout } from './layout';
export { stepNames, type StepName } from './names';
export {
  HISTORY_LIMIT,
  canRedo,
  canUndo,
  record,
  redo,
  reset,
  startHistory,
  undo,
  type History,
} from './history';
export * from './canvas';
