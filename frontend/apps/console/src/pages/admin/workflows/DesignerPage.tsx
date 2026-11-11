import { ApartmentOutlined, BranchesOutlined, RedoOutlined, UndoOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Alert, App, Button, Flex, Skeleton, Space, Tabs, Typography, theme } from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react';
import { useNavigate, useParams } from 'react-router';

import {
  useEnableWorkflow,
  useNodePorts,
  useNodeTypes,
  usePublishWorkflow,
  useSaveDraft,
  useWorkflow,
  type NodeTypeOut,
  type WorkflowOut,
} from '@supportx/api-client';
import {
  Background,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  ROW,
  applyEdgeChanges,
  applyNodeChanges,
  canRedo,
  canUndo,
  fromGraph,
  readDefinition,
  record,
  redo,
  startHistory,
  toGraph,
  undo,
  useReactFlow,
  withLayout,
  type Connection,
  type EdgeChange,
  type FlowDefinition,
  type History,
  type NodeChange,
  type WorkflowEdge,
  type WorkflowNode,
} from '@supportx/flow';
import { useListChannel } from '@supportx/realtime';
import {
  HeaderActions,
  NoAccess,
  RecordHeader,
  ToneTag,
  WriteButton,
  reportError,
  useAccess,
  useAppearance,
  useLabel,
  useMinWidth,
  usePageCrumbs,
} from '@supportx/ui';

import { freeId, problemText } from './nodes';
import { NodeView } from './NodeView';
import { DRAG_TYPE, Palette } from './Palette';
import { LinkDetails, NodeDetails, Outline, type NodeProblem } from './SidePanels';
import { TestPanel, type TestHighlight } from './TestPanel';
import { WorkflowState } from './WorkflowsPage';

interface Graph {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

const NODE_TYPES = { workflow: NodeView };

/**
 * Admin › Workflows › one workflow: the designer (WP-048b S4; REQ-WF-008, -019, -028).
 * "Template A header + canvas body": the shared RecordHeader with the workflow's name, state
 * and actions on one row; below it the palette, the canvas and the details, outline and
 * problems. Every edit can be undone (at least 50 steps, REQ-WF-008 AC2). Saving keeps the
 * draft whatever its problems, which come back onto the canvas (REQ-WF-019). Live: another
 * admin's save shows at once when nothing is unsaved here, else a notice offers to reload.
 */
export function DesignerPage() {
  const t = useLabel();
  const { can } = useAccess();
  const { workflowId = '' } = useParams();
  const found = useWorkflow(can('workflows.manage') ? workflowId : '');
  if (!can('workflows.manage')) return <NoAccess titleKey="nav.admin_workflows" />;
  if (found.isPending) return <Skeleton active data-testid="designer-loading" />;
  if (found.data === undefined) {
    return (
      <Alert
        type="error"
        showIcon
        message={t('workflows.designer.not_found')}
        data-testid="designer-not-found"
      />
    );
  }
  return (
    <ReactFlowProvider>
      <Designer workflow={found.data} />
    </ReactFlowProvider>
  );
}

function Designer({ workflow }: { workflow: WorkflowOut }) {
  const t = useLabel();
  const { message } = App.useApp();
  const { token } = theme.useToken();
  const { direction, mode } = useAppearance();
  const rtl = direction === 'rtl';
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // Side by side from 1100 px (canvas and details); the palette gets its own pane only from
  // 1600 px, so the canvas is never squeezed beside the admin menu (the 1280 matrix shot).
  const wide = useMinWidth(1100);
  const widest = useMinWidth(1600);
  const flow = useReactFlow<WorkflowNode, WorkflowEdge>();
  const types = useNodeTypes(workflow.record_type);
  const ports = useNodePorts();
  const save = useSaveDraft();
  const publish = usePublishWorkflow();
  const enable = useEnableWorkflow();
  usePageCrumbs([
    { label: t('nav.admin_workflows'), path: '/admin/workflows' },
    { label: workflow.name },
  ]);

  const catalogue = useMemo(
    () => new Map<string, NodeTypeOut>((types.data ?? []).map((n) => [n.type, n])),
    [types.data],
  );
  const staticPorts = useCallback(
    (type: string) => [...(catalogue.get(type)?.outputs ?? [])],
    [catalogue],
  );
  const saved = useMemo(() => readDefinition(workflow.draft), [workflow.draft]);
  const graphOf = useCallback(
    (definition: FlowDefinition): Graph =>
      toGraph(definition, { ports: (n) => staticPorts(n.type), rtl }),
    [rtl, staticPorts],
  );
  const [history, setHistory] = useState<History<Graph>>(() => startHistory(graphOf(saved)));
  const [live, setLive] = useState<Graph>(history.present);
  const [selected, setSelected] = useState<{ kind: 'node' | 'edge'; id: string }>();
  const [tab, setTab] = useState('details');
  const [stale, setStale] = useState(false);
  const [highlight, setHighlight] = useState<TestHighlight | null>(null);
  const definitionOf = useCallback(
    (graph: Graph) => fromGraph(saved, graph.nodes, graph.edges, { rtl }),
    [saved, rtl],
  );
  const dirty = JSON.stringify(definitionOf(live)) !== JSON.stringify(saved);

  // A new saved draft (ours, or another admin's while nothing is unsaved here) replaces the
  // canvas; the history starts again from it.
  const loadedVersion = useRef(workflow.version);
  useEffect(() => {
    if (workflow.version === loadedVersion.current) return;
    loadedVersion.current = workflow.version;
    const fresh = graphOf(saved);
    setHistory(startHistory(fresh));
    setLive(fresh);
    setStale(false);
  }, [workflow.version, saved, graphOf]);

  // Outputs that depend on settings (a switch's cases, a wait's timeout) from the server.
  const configKey = JSON.stringify(live.nodes.map((n) => [n.data.nodeType, n.data.config]));
  const { mutate: askPorts } = ports;
  useEffect(() => {
    const nodes = live.nodes.map((n) => ({ type: n.data.nodeType, config: n.data.config }));
    if (nodes.length === 0) return;
    askPorts(nodes, {
      onSuccess: (found) => {
        setLive((g) => ({
          ...g,
          nodes: g.nodes.map((n, i) => {
            const outputs = found[i]?.outputs;
            return outputs === undefined || JSON.stringify(outputs) === JSON.stringify(n.data.ports)
              ? n
              : { ...n, data: { ...n.data, ports: outputs } };
          }),
        }));
      },
    });
    // configKey stands for the nodes' types and settings; positions do not change outputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see the line above
  }, [configKey, askPorts]);

  useListChannel('workflows', (m) => {
    if (m.type !== 'workflows.changed' || !m.ids.includes(workflow.id)) return;
    if ((m.version ?? 0) <= workflow.version) return; // our own save, already here
    if (dirty) setStale(true);
    else void queryClient.invalidateQueries({ queryKey: ['workflows', 'detail', workflow.id] });
  });

  const problems = useMemo(() => workflow.problems ?? [], [workflow.problems]);
  const nodeProblems = useMemo(() => {
    const byNode = new Map<string, NodeProblem[]>();
    for (const p of problems) {
      if (!p.where.startsWith('node:')) continue;
      const id = p.where.slice(5);
      byNode.set(id, [...(byNode.get(id) ?? []), { code: p.code, params: p.params ?? {} }]);
    }
    return byNode;
  }, [problems]);
  const shown: Graph = useMemo(
    () => ({
      nodes: live.nodes.map((n) => ({
        ...n,
        selected: selected?.kind === 'node' && selected.id === n.id,
        data: {
          ...n.data,
          problems: nodeProblems.get(n.id)?.length ?? 0,
          // A test run's path and where it is now (REQ-WF-022 AC1: the path taken).
          state: highlight?.at.has(n.id)
            ? ('current' as const)
            : highlight?.passed.has(n.id)
              ? ('passed' as const)
              : undefined,
        },
      })),
      edges: live.edges.map((e) => ({
        ...e,
        selected: selected?.kind === 'edge' && selected.id === e.id,
        label: undefined,
      })),
    }),
    [live, nodeProblems, selected, highlight],
  );

  // One edit: what is drawn becomes the next step of the history.
  const commit = useCallback((next: Graph) => {
    setLive(next);
    setHistory((h) => record(h, next));
  }, []);
  const step = (move: typeof undo) => {
    setHistory((h) => {
      const moved = move(h);
      setLive(moved.present);
      return moved;
    });
  };

  const readOnly = false;
  const addNode = (type: string, at?: { x: number; y: number }) => {
    const taken = new Set(live.nodes.map((n) => n.id));
    const id = freeId(type, taken);
    const anchor = live.nodes.find((n) => selected?.kind === 'node' && n.id === selected.id);
    const position =
      at ??
      (anchor === undefined
        ? flow.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 })
        : { x: anchor.position.x, y: anchor.position.y + ROW });
    const node: WorkflowNode = {
      id,
      type: 'workflow',
      position,
      data: { nodeType: type, config: {}, ports: staticPorts(type) },
    };
    commit({ ...live, nodes: [...live.nodes, node] });
    setSelected({ kind: 'node', id });
    setTab('details');
  };
  const link = (from: string, port: string, to: string | null) => {
    // One link per output: a new one replaces the old.
    const others = live.edges.filter(
      (e) => !(e.source === from && (e.data?.port ?? e.sourceHandle) === port),
    );
    const added: WorkflowEdge[] =
      to === null
        ? []
        : [
            {
              id: `${from}:${port}->${to}`,
              source: from,
              sourceHandle: port,
              target: to,
              targetHandle: 'in',
              data: { port },
            },
          ];
    commit({ ...live, edges: [...others, ...added] });
  };
  const removeNode = (id: string) => {
    commit({
      nodes: live.nodes.filter((n) => n.id !== id),
      edges: live.edges.filter((e) => e.source !== id && e.target !== id),
    });
    setSelected(undefined);
  };
  const removeEdge = (id: string) => {
    commit({ ...live, edges: live.edges.filter((e) => e.id !== id) });
    setSelected(undefined);
  };

  const onNodesChange = (changes: NodeChange<WorkflowNode>[]) => {
    const kept = changes.filter((c) => c.type !== 'select');
    for (const c of changes) {
      if (c.type === 'select' && c.selected) setSelected({ kind: 'node', id: c.id });
    }
    if (kept.length === 0) return;
    const removed = new Set(kept.flatMap((c) => (c.type === 'remove' ? [c.id] : [])));
    if (removed.has('start')) return; // the start stays: a workflow always has one
    const nodes = applyNodeChanges(kept, live.nodes);
    const next = {
      nodes,
      edges:
        removed.size === 0
          ? live.edges
          : live.edges.filter((e) => !removed.has(e.source) && !removed.has(e.target)),
    };
    // A drag is one step, when it ends; the moves in between only redraw.
    const settled = kept.some(
      (c) =>
        c.type === 'remove' || c.type === 'add' || (c.type === 'position' && c.dragging === false),
    );
    if (settled) commit(next);
    else setLive(next);
  };
  const onEdgesChange = (changes: EdgeChange<WorkflowEdge>[]) => {
    for (const c of changes) {
      if (c.type === 'select' && c.selected) setSelected({ kind: 'edge', id: c.id });
    }
    const kept = changes.filter((c) => c.type !== 'select');
    if (kept.length > 0) commit({ ...live, edges: applyEdgeChanges(kept, live.edges) });
  };
  const onConnect = (c: Connection) => {
    if (c.sourceHandle === null) return;
    link(c.source, c.sourceHandle, c.target);
  };
  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    const type = event.dataTransfer.getData(DRAG_TYPE);
    if (type === '') return;
    event.preventDefault();
    addNode(type, flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }));
  };
  const autoLayout = () => {
    const laid = graphOf(withLayout(definitionOf(live)));
    commit({
      ...live,
      nodes: live.nodes.map((n) => ({
        ...n,
        position: laid.nodes.find((l) => l.id === n.id)?.position ?? n.position,
      })),
    });
    window.requestAnimationFrame(() => void flow.fitView({ padding: 0.2 }));
  };

  // Undo and redo from the keyboard, as in any editor (not while typing in a field).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, [contenteditable="true"]')) return;
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'z') {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') {
          event.preventDefault();
          step(redo);
        }
        return;
      }
      event.preventDefault();
      step(event.shiftKey ? redo : undo);
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
    };
  });

  const doSave = () => {
    save.mutate(
      { id: workflow.id, version: workflow.version, definition: { ...definitionOf(live) } },
      {
        onSuccess: (out) => {
          const count = out.problems?.length ?? 0;
          void message.success(
            count === 0
              ? t('workflows.designer.saved')
              : t('workflows.designer.saved_problems', { count }),
          );
        },
        onError: reportError,
      },
    );
  };
  const doPublish = () => {
    publish.mutate(
      { id: workflow.id, version: workflow.version },
      {
        onSuccess: (out) => {
          void message.success(
            t('workflows.designer.published', { n: out.published_version ?? 0 }),
          );
        },
        onError: reportError,
      },
    );
  };
  const publishWhyNot = dirty
    ? t('workflows.designer.why.save_first')
    : problems.length > 0
      ? t('workflows.designer.why.problems', { count: problems.length })
      : undefined;

  const selectedNode = live.nodes.find((n) => selected?.kind === 'node' && n.id === selected.id);
  const selectedEdge = live.edges.find((e) => selected?.kind === 'edge' && e.id === selected.id);
  const typeOf = (id: string) => live.nodes.find((n) => n.id === id)?.data.nodeType ?? '';
  const otherProblems = problems.filter((p) => !p.where.startsWith('node:'));

  const sideItems = [
    {
      key: 'details',
      label: t('workflows.designer.details'),
      children:
        selectedNode !== undefined ? (
          <NodeDetails
            // A new node or new settings start the editor afresh (no effect to sync it).
            key={`${selectedNode.id}:${JSON.stringify(selectedNode.data.config)}`}
            node={selectedNode}
            recordType={workflow.record_type}
            problems={nodeProblems.get(selectedNode.id) ?? []}
            readOnly={readOnly}
            onConfig={(config) => {
              commit({
                ...live,
                nodes: live.nodes.map((n) =>
                  n.id === selectedNode.id ? { ...n, data: { ...n.data, config } } : n,
                ),
              });
            }}
            onDelete={() => {
              removeNode(selectedNode.id);
            }}
          />
        ) : selectedEdge !== undefined ? (
          <LinkDetails
            edge={selectedEdge}
            typeOf={typeOf}
            readOnly={readOnly}
            onDelete={() => {
              removeEdge(selectedEdge.id);
            }}
          />
        ) : (
          <Typography.Text type="secondary">{t('workflows.designer.select_hint')}</Typography.Text>
        ),
    },
    {
      key: 'outline',
      label: t('workflows.designer.outline'),
      children: (
        <Outline
          nodes={live.nodes}
          edges={live.edges}
          readOnly={readOnly}
          onLink={link}
          onSelect={(id) => {
            setSelected({ kind: 'node', id });
            setTab('details');
          }}
        />
      ),
    },
    {
      key: 'problems',
      label: t('workflows.designer.problems_tab', { count: problems.length }),
      children:
        problems.length === 0 ? (
          <Typography.Text type="secondary" data-testid="designer-no-problems">
            {t('workflows.designer.no_problems')}
          </Typography.Text>
        ) : (
          <ul style={{ margin: 0, paddingInlineStart: 16 }} data-testid="designer-problems">
            {problems.map((p, i) => {
              const node = p.where.startsWith('node:') ? p.where.slice(5) : undefined;
              const text = problemText(t, p.code, p.params ?? {});
              return (
                <li key={`${p.where}-${p.code}-${String(i)}`}>
                  {node === undefined ? (
                    text
                  ) : (
                    // Choosing a problem selects its node (ADR-043 §2).
                    <Button
                      type="link"
                      style={{
                        padding: 0,
                        height: 'auto',
                        whiteSpace: 'normal',
                        textAlign: 'start',
                      }}
                      onClick={() => {
                        setSelected({ kind: 'node', id: node });
                        setTab('details');
                        const target = live.nodes.find((n) => n.id === node);
                        if (target !== undefined) {
                          void flow.setCenter(target.position.x, target.position.y, {
                            zoom: 1,
                          });
                        }
                      }}
                    >
                      {t('workflows.designer.problem_at', { node, text })}
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        ),
    },
    {
      key: 'test',
      label: t('workflows.test.tab'),
      children: (
        <TestPanel workflow={workflow} dirty={dirty} typeOf={typeOf} onHighlight={setHighlight} />
      ),
    },
  ];

  const palette = (
    <Palette
      types={types.data ?? []}
      onAdd={(type) => {
        addNode(type);
      }}
      readOnly={readOnly}
    />
  );

  const card = {
    background: token.colorBgContainer,
    border: `1px solid ${token.colorBorderSecondary}`,
    borderRadius: token.borderRadius,
  } as const;

  return (
    <Flex vertical gap={16} data-testid="workflow-designer" style={{ minWidth: 0 }}>
      <section style={{ ...card, padding: '16px 18px' }}>
        <Flex wrap gap={16} align="flex-start">
          <div style={{ flex: '999 1 420px', minWidth: 0 }}>
            <RecordHeader
              icon={<ApartmentOutlined />}
              typeLabel={t('workflows.type_label')}
              displayId={t(`work_item_type.${workflow.record_type}`)}
              copyable={false}
              title={workflow.name}
              tags={
                <Space wrap>
                  <WorkflowState workflow={workflow} />
                  {workflow.published_version !== null && (
                    <ToneTag tone="default">
                      {t('workflows.version_n', { n: workflow.published_version })}
                    </ToneTag>
                  )}
                  {dirty && <ToneTag tone="warning">{t('workflows.designer.unsaved')}</ToneTag>}
                  {problems.length > 0 && (
                    <ToneTag tone="error" testId="designer-problem-count">
                      {t('workflows.designer.problems_tab', { count: problems.length })}
                    </ToneTag>
                  )}
                </Space>
              }
              testId="designer-header"
            />
          </div>
          <div style={{ flex: '1 1 auto' }}>
            <HeaderActions
              testId="designer-actions"
              primary={
                <WriteButton
                  type="primary"
                  loading={save.isPending}
                  disabled={!dirty}
                  whyDisabled={t('workflows.designer.why.nothing_to_save')}
                  onClick={doSave}
                  data-testid="designer-save"
                >
                  {t('actions.save')}
                </WriteButton>
              }
              buttons={[
                {
                  key: 'publish',
                  node: (
                    <WriteButton
                      loading={publish.isPending}
                      disabled={publishWhyNot !== undefined}
                      whyDisabled={publishWhyNot}
                      onClick={doPublish}
                      data-testid="designer-publish"
                    >
                      {t('workflows.designer.publish')}
                    </WriteButton>
                  ),
                },
              ]}
              more={[
                {
                  key: 'enable',
                  label: workflow.enabled
                    ? t('workflows.designer.disable')
                    : t('workflows.designer.enable'),
                  disabled: workflow.published_version === null,
                  onClick: () => {
                    enable.mutate(
                      { id: workflow.id, version: workflow.version, enabled: !workflow.enabled },
                      { onError: reportError },
                    );
                  },
                  testId: 'designer-enable',
                },
                {
                  key: 'back',
                  label: t('workflows.designer.back'),
                  onClick: () => void navigate('/admin/workflows'),
                  testId: 'designer-back',
                },
              ]}
            />
          </div>
        </Flex>
      </section>
      {stale && (
        <Alert
          type="warning"
          showIcon
          message={t('workflows.designer.changed_elsewhere')}
          action={
            <Button
              size="small"
              onClick={() => {
                setStale(false);
                void queryClient.invalidateQueries({
                  queryKey: ['workflows', 'detail', workflow.id],
                });
              }}
              data-testid="designer-reload"
            >
              {t('workflows.designer.reload')}
            </Button>
          }
          data-testid="designer-stale"
        />
      )}
      {otherProblems.length > 0 && (
        <Alert
          type="error"
          showIcon
          message={otherProblems.map((p) => problemText(t, p.code, p.params ?? {})).join(' ')}
        />
      )}
      <Flex gap={16} vertical={!wide} style={{ minWidth: 0 }}>
        {widest && (
          <aside
            style={{
              ...card,
              width: 220,
              flexShrink: 0,
              padding: 12,
              overflowY: 'auto',
              maxHeight: '70vh',
            }}
          >
            {palette}
          </aside>
        )}
        <div
          style={{
            ...card,
            flex: 1,
            minWidth: 0,
            height: wide ? '70vh' : '60vh',
            minHeight: 420,
          }}
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes(DRAG_TYPE)) e.preventDefault();
          }}
          onDrop={onDrop}
          data-testid="designer-canvas"
        >
          <ReactFlow<WorkflowNode, WorkflowEdge>
            nodes={shown.nodes}
            edges={shown.edges}
            nodeTypes={NODE_TYPES}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            isValidConnection={(c) => c.source !== c.target && typeOf(c.target) !== 'start'}
            onPaneClick={() => {
              setSelected(undefined);
            }}
            deleteKeyCode={['Delete', 'Backspace']}
            fitView
            colorMode={mode === 'dark' ? 'dark' : 'light'}
            // Fit again once the pane has its size (a narrow screen lays it out after the nodes).
            onInit={(instance) => {
              window.requestAnimationFrame(() => void instance.fitView({ padding: 0.2 }));
            }}
            minZoom={0.2}
            proOptions={{ hideAttribution: true }}
            aria-label={t('workflows.designer.canvas')}
          >
            <Background gap={20} />
            <Controls position={rtl ? 'bottom-right' : 'bottom-left'} />
            <MiniMap position={rtl ? 'bottom-left' : 'bottom-right'} pannable zoomable />
            <Panel position={rtl ? 'top-right' : 'top-left'}>
              <Space wrap>
                <Button
                  size="small"
                  icon={<UndoOutlined />}
                  disabled={!canUndo(history)}
                  onClick={() => {
                    step(undo);
                  }}
                  data-testid="designer-undo"
                >
                  {t('workflows.designer.undo')}
                </Button>
                <Button
                  size="small"
                  icon={<RedoOutlined />}
                  disabled={!canRedo(history)}
                  onClick={() => {
                    step(redo);
                  }}
                  data-testid="designer-redo"
                >
                  {t('workflows.designer.redo')}
                </Button>
                <Button
                  size="small"
                  icon={<BranchesOutlined />}
                  onClick={autoLayout}
                  data-testid="designer-layout"
                >
                  {t('workflows.designer.auto_layout')}
                </Button>
              </Space>
            </Panel>
          </ReactFlow>
        </div>
        <aside
          style={{
            ...card,
            width: wide ? 340 : undefined,
            flexShrink: 0,
            padding: 12,
            overflowY: 'auto',
            maxHeight: wide ? '70vh' : undefined,
          }}
        >
          <Tabs
            activeKey={widest && tab === 'palette' ? 'details' : tab}
            onChange={setTab}
            size="small"
            // Narrower, the palette joins the tabs (one row, never tabs inside tabs).
            items={
              widest
                ? sideItems
                : [
                    { key: 'palette', label: t('workflows.designer.palette'), children: palette },
                    ...sideItems,
                  ]
            }
          />
        </aside>
      </Flex>
    </Flex>
  );
}
