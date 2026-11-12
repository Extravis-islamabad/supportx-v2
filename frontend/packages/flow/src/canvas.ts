// The React Flow parts the designer uses, through this package only: one place pins the
// library (§3 "React Flow (xyflow)"), the apps never import it directly.
import '@xyflow/react/dist/style.css';

export {
  Background,
  BackgroundVariant,
  Controls,
  ControlButton,
  Handle,
  MarkerType,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  useNodesInitialized,
  useReactFlow,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type NodeProps,
  type OnSelectionChangeParams,
} from '@xyflow/react';
