// @supportx/flow: React Flow parts for workflows, life cycles and CMDB maps (architecture.md §6.7).
// WP-048b S4: the workflow definition, its mapping to the canvas, and the automatic layout.
export {
  emptyDefinition,
  readDefinition,
  readVariables,
  VARIABLE_KINDS,
  type FlowDefinition,
  type FlowLinkDef,
  type FlowNodeDef,
  type FlowPosition,
  type VariableKind,
  type WorkflowVariable,
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
export { COLUMN, freeSpot, ROW, layout, withLayout } from './layout';
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
export {
  CI_MAP_LAYOUTS,
  MAP_COLUMN,
  MAP_NODE_HEIGHT,
  MAP_NODE_WIDTH,
  MAP_RING,
  MAP_ROW,
  isMapArrow,
  layoutMap,
  mirrored,
  nextNode,
  type CiMapLayout,
  type MapArrow,
  type MapLayoutInput,
  type MapLink,
  type MapPoint,
} from './ciMap';
export {
  CSV_BOM,
  csvCell,
  mapCsv,
  mapSvg,
  toCsv,
  xmlEscape,
  type MapCsvEdge,
  type MapCsvNode,
  type MapCsvWords,
  type SvgEdge,
  type SvgMap,
  type SvgNode,
} from './ciExport';
