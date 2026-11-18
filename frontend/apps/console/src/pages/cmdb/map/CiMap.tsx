import {
  CheckCircleOutlined,
  DownloadOutlined,
  LockOutlined,
  StopOutlined,
} from '@ant-design/icons';
import { Alert, App, Button, Flex, List, Space, Typography, theme } from 'antd';
import {
  memo,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { Link } from 'react-router';

import { useRemoveRelationship, type RelationshipType } from '@supportx/api-client';
import {
  Background,
  Controls,
  Handle,
  MAP_NODE_HEIGHT,
  MAP_NODE_WIDTH,
  MarkerType,
  Panel,
  Position,
  ReactFlow,
  isMapArrow,
  layoutMap,
  mapCsv,
  mapSvg,
  mirrored,
  nextNode,
  useNodesInitialized,
  useReactFlow,
  type CiMapLayout,
  type Edge,
  type MapPoint,
  type Node,
  type NodeChange,
  type NodeProps,
} from '@supportx/flow';
import { TAG_TONES, ToneTag, reportError, useAppearance, useLabel } from '@supportx/ui';

import type { MapGraph, ShownEdge, ShownNode } from './useMapGraph';
import { nodeAriaLabel, nodeLook, nodeName, nodeState, nodeType, relationshipName } from './words';

const FIT = { padding: 0.2, maxZoom: 1 } as const;

interface CiNodeData extends Record<string, unknown> {
  shown: ShownNode;
  title: string;
  subtitle: string;
  /** Open incidents, problems and changes, once the counts port answers (REQ-CMDB-009). */
  counts: { incident: number; problem: number; change: number } | null;
  base: boolean;
}

type CiFlowNode = Node<CiNodeData, 'ci'>;

export interface CiMapProps {
  baseKey: string;
  graph: MapGraph;
  types: readonly RelationshipType[];
  layout: CiMapLayout;
  /** Positions to start from (a business view's pinned ones); the rest are laid out. */
  pinned?: ReadonlyMap<string, MapPoint>;
  expanded: ReadonlySet<string>;
  onExpand: (key: string) => void;
  /** The person may change the base CI: remove offers itself on its links. */
  canEdit: boolean;
  /** The positions now on the map, stored left to right (a business view saves them). */
  onPositions?: (positions: ReadonlyMap<string, MapPoint>) => void;
  /** File names of the exports, e.g. the base CI's display ID. */
  fileName: string;
  testId?: string;
}

/**
 * A CI's relationship map (WP-053 S2, REQ-CMDB-008; lane C's conditions 5 to 12) on React Flow,
 * through @supportx/flow as the workflow designer is. Laid out by the package's pure layouts;
 * expanding a node never moves one already placed. Keyboard: every node is focusable, the
 * arrows move by what is drawn (mirrored in RTL), Home goes back to the base, Enter opens the
 * node's menu and Escape closes only that menu. A "Skip to the list" link leads to the same
 * nodes and links as a list. Right to left mirrors the x-coordinates, never the canvas.
 */
export function CiMap(props: CiMapProps) {
  const { baseKey, graph, types, layout, pinned, expanded, onExpand, canEdit, onPositions } = props;
  const t = useLabel();
  const { modal, message } = App.useApp();
  const { token } = theme.useToken();
  const { direction, mode, locale, intlLocale } = useAppearance();
  const rtl = direction === 'rtl';
  const container = useRef<HTMLDivElement>(null);
  const remove = useRemoveRelationship();
  const [menu, setMenu] = useState<string | null>(null);
  const typeOf = useMemo(() => new Map(types.map((x) => [x.id, x])), [types]);
  const listId = `ci-map-list-${baseKey}`;

  // Where nodes are (left to right), remembered between answers: new nodes only find room
  // around those already placed (AC1); a layout change lays the map out afresh. React's "adjust
  // state while rendering" pattern (no effect), so a new answer never flashes the old layout.
  const keys = useMemo(() => graph.nodes.map((n) => n.key), [graph.nodes]);
  const links = useMemo(() => graph.edges.map((e) => ({ from: e.from, to: e.to })), [graph.edges]);
  const [laid, setLaid] = useState(() => ({
    keys,
    links,
    layout,
    positions: layoutMap({
      base: baseKey,
      keys,
      links,
      layout,
      placed: pinned === undefined || pinned.size === 0 ? undefined : pinned,
    }),
  }));
  let positions = laid.positions;
  if (laid.keys !== keys || laid.links !== links || laid.layout !== layout) {
    positions = layoutMap({
      base: baseKey,
      keys,
      links,
      layout,
      placed: laid.layout === layout ? laid.positions : undefined,
    });
    setLaid({ keys, links, layout, positions });
  }
  useEffect(() => {
    onPositions?.(positions);
  }, [positions, onPositions]);
  const shown = useMemo(() => mirrored(positions, rtl), [positions, rtl]);

  const linkCount = useMemo(() => {
    const count = new Map<string, number>();
    for (const e of graph.edges) {
      count.set(e.from, (count.get(e.from) ?? 0) + 1);
      count.set(e.to, (count.get(e.to) ?? 0) + 1);
    }
    return count;
  }, [graph.edges]);
  const byKey = useMemo(() => new Map(graph.nodes.map((n) => [n.key, n])), [graph.nodes]);
  const relName = (e: ShownEdge) =>
    relationshipName(t, locale, typeOf.get(e.edge.type_id), 'forward');

  const nodes: CiFlowNode[] = graph.nodes.map((n) => {
    const at = shown.get(n.key) ?? { x: 0, y: 0 };
    const type = nodeType(t, locale, n.node);
    const state = nodeState(t, locale, n.node);
    return {
      id: n.key,
      type: 'ci',
      position: at,
      width: MAP_NODE_WIDTH,
      height: MAP_NODE_HEIGHT,
      ariaLabel: nodeAriaLabel(t, locale, n.node, linkCount.get(n.key) ?? 0),
      // The menu opens on Enter (the map's own key handler); React Flow's keys stay off.
      selectable: false,
      data: {
        shown: n,
        title: nodeName(t, n.node),
        subtitle: [type, state].filter((x) => x !== '').join(' · '),
        counts: graph.countsAvailable ? (n.node.counts ?? null) : null,
        base: n.key === baseKey,
      },
    };
  });
  const edges: Edge[] = graph.edges.map((e) => {
    const name = relName(e);
    const from = byKey.get(e.from);
    const to = byKey.get(e.to);
    return {
      id: e.key,
      source: e.from,
      target: e.to,
      type: 'straight',
      label: name,
      markerEnd: { type: MarkerType.ArrowClosed },
      // Never React Flow's own "Edge from <id> to <id>": the link in words.
      ariaLabel: t('cmdb.map.edge_aria', {
        from: from === undefined ? '' : nodeName(t, from.node),
        relationship: name,
        to: to === undefined ? '' : nodeName(t, to.node),
      }),
      focusable: false,
    };
  });

  const focusNode = (key: string) => {
    const found = [
      ...(container.current?.querySelectorAll<HTMLElement>('.react-flow__node') ?? []),
    ].find((el) => el.dataset.id === key);
    found?.focus();
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const el = (event.target as HTMLElement).closest<HTMLElement>('.react-flow__node');
    const key = el?.dataset.id;
    if (key === undefined) return;
    if (isMapArrow(event.key)) {
      const next = nextNode(key, shown, event.key);
      event.preventDefault();
      if (next !== undefined) focusNode(next);
    } else if (event.key === 'Home') {
      event.preventDefault();
      focusNode(baseKey);
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      // A CI you can't open has no actions (condition 8).
      if (byKey.get(key)?.node.restricted !== true) setMenu(key);
    }
  };

  const closeMenu = () => {
    const key = menu;
    setMenu(null);
    if (key !== null) {
      window.requestAnimationFrame(() => {
        focusNode(key);
      });
    }
  };

  const askRemove = (e: ShownEdge) => {
    const from = byKey.get(e.from);
    const to = byKey.get(e.to);
    const version = e.edge.version;
    const id = e.edge.id;
    if (id == null || version == null) return;
    modal.confirm({
      title: t('cmdb.map.remove_confirm', {
        from: from === undefined ? '' : nodeName(t, from.node),
        relationship: relName(e),
        to: to === undefined ? '' : nodeName(t, to.node),
      }),
      content: t('cmdb.map.remove_confirm_detail'),
      okText: t('cmdb.map.remove'),
      okButtonProps: { danger: true, 'data-testid': 'ci-map-remove-ok' },
      cancelText: t('actions.cancel'),
      onOk: () =>
        remove
          .mutateAsync({
            id,
            version,
            ciIds: [from?.node.id, to?.node.id].filter((x): x is string => x != null),
          })
          .then(() => {
            void message.success(t('cmdb.map.removed'));
          }, reportError),
    });
  };

  const exportCsv = () => {
    const words = {
      header: [
        t('cmdb.map.csv.from_id'),
        t('cmdb.map.csv.from_name'),
        t('cmdb.map.csv.from_type'),
        t('cmdb.map.csv.from_state'),
        t('cmdb.map.csv.relationship'),
        t('cmdb.map.csv.to_id'),
        t('cmdb.map.csv.to_name'),
        t('cmdb.map.csv.to_type'),
        t('cmdb.map.csv.to_state'),
      ] as const,
      restricted: t('cmdb.map.csv.restricted'),
    };
    const end = (n: ShownNode | undefined) =>
      n === undefined || n.node.restricted
        ? { restricted: true }
        : {
            restricted: false,
            displayId: n.node.display_id ?? '',
            name: n.node.name ?? '',
            type: nodeType(t, locale, n.node),
            state: nodeState(t, locale, n.node),
          };
    const csv = mapCsv(
      graph.edges.map((e) => ({
        from: end(byKey.get(e.from)),
        relationship: relName(e),
        to: end(byKey.get(e.to)),
      })),
      words,
    );
    saveText(`${props.fileName}-map.csv`, csv, 'text/csv;charset=utf-8');
  };

  const exportSvg = () => {
    const tones = TAG_TONES[mode];
    const svg = mapSvg({
      title: t('cmdb.map.svg_title', { name: props.fileName }),
      background: mode === 'dark' ? '#141414' : '#ffffff',
      line: '#8c8c8c',
      rtl,
      nodes: nodes.map((n) => {
        const look = nodeLook(n.data.shown.node);
        return {
          x: n.position.x,
          y: n.position.y,
          width: MAP_NODE_WIDTH,
          height: MAP_NODE_HEIGHT,
          title: n.data.title,
          subtitle: n.data.subtitle,
          fill: tones[look.tone].background,
          stroke: tones[look.tone].border,
          text: tones[look.tone].color,
          dashed: look.border !== 'solid',
        };
      }),
      edges: graph.edges.flatMap((e) => {
        const a = shown.get(e.from);
        const b = shown.get(e.to);
        if (a === undefined || b === undefined) return [];
        return [
          {
            x1: a.x + MAP_NODE_WIDTH / 2,
            y1: a.y + MAP_NODE_HEIGHT / 2,
            x2: b.x + MAP_NODE_WIDTH / 2,
            y2: b.y + MAP_NODE_HEIGHT / 2,
            label: relName(e),
          },
        ];
      }),
    });
    saveText(`${props.fileName}-map.svg`, svg, 'image/svg+xml');
  };

  const onNodesChange = (changes: NodeChange<CiFlowNode>[]) => {
    const moved = changes.flatMap((c) =>
      c.type === 'position' && c.position !== undefined ? [{ id: c.id, at: c.position }] : [],
    );
    if (moved.length === 0) return;
    setLaid((before) => {
      const next = new Map(before.positions);
      for (const { id, at } of moved) {
        // Stored left to right: a node dragged in RTL is mirrored back.
        next.set(id, { x: Math.round(rtl ? -at.x : at.x), y: Math.round(at.y) });
      }
      return { ...before, positions: next };
    });
  };

  const menuNode = menu === null ? undefined : byKey.get(menu);
  const menuEdges =
    menu === null
      ? []
      : graph.edges.filter((e) => (e.from === menu || e.to === menu) && e.edge.id != null);
  const count = new Intl.NumberFormat(intlLocale).format(graph.nodes.length);

  return (
    <Flex vertical gap={12} data-testid={props.testId ?? 'ci-map'}>
      <style>{`.sx-ci-map .react-flow__node:focus-visible { outline: 2px solid ${token.colorPrimary}; outline-offset: 2px; border-radius: ${String(token.borderRadiusLG)}px; }`}</style>
      <Flex gap={8} wrap align="center" justify="space-between">
        <a href={`#${listId}`} className="sx-edit-trigger" data-testid="ci-map-skip">
          {t('cmdb.map.skip_to_list')}
        </a>
        <Space wrap>
          <Button
            size="small"
            icon={<DownloadOutlined />}
            onClick={exportCsv}
            data-testid="ci-map-export-csv"
          >
            {t('cmdb.map.export_csv')}
          </Button>
          <Button
            size="small"
            icon={<DownloadOutlined />}
            onClick={exportSvg}
            data-testid="ci-map-export-svg"
          >
            {t('cmdb.map.export_svg')}
          </Button>
        </Space>
      </Flex>
      {graph.truncated && (
        <Alert
          type="info"
          showIcon
          message={t('cmdb.map.truncated', { count })}
          data-testid="ci-map-truncated"
        />
      )}
      <div
        ref={container}
        className="sx-ci-map"
        onKeyDown={onKeyDown}
        style={{
          height: '60vh',
          minHeight: 420,
          border: `1px solid ${token.colorBorderSecondary}`,
          borderRadius: token.borderRadius,
          background: token.colorBgContainer,
        }}
        data-testid="ci-map-canvas"
      >
        <ReactFlow<CiFlowNode>
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          onNodesChange={onNodesChange}
          nodesConnectable={false}
          edgesFocusable={false}
          disableKeyboardA11y
          deleteKeyCode={null}
          fitView
          fitViewOptions={FIT}
          minZoom={0.1}
          colorMode={mode === 'dark' ? 'dark' : 'light'}
          proOptions={{ hideAttribution: true }}
          aria-label={t('cmdb.map.canvas')}
          ariaLabelConfig={{
            'node.a11yDescription.default': t('cmdb.map.keyboard_help'),
            'node.a11yDescription.keyboardDisabled': t('cmdb.map.keyboard_help'),
            'edge.a11yDescription.default': t('cmdb.map.keyboard_help'),
            'controls.ariaLabel': t('cmdb.map.controls'),
            'controls.zoomIn.ariaLabel': t('cmdb.map.zoom_in'),
            'controls.zoomOut.ariaLabel': t('cmdb.map.zoom_out'),
            'controls.fitView.ariaLabel': t('cmdb.map.fit'),
            'controls.interactive.ariaLabel': t('cmdb.map.lock'),
            'minimap.ariaLabel': t('cmdb.map.canvas'),
            'handle.ariaLabel': t('cmdb.map.canvas'),
          }}
        >
          <Background gap={20} />
          <FitWhenReady />
          <Controls position={rtl ? 'bottom-right' : 'bottom-left'} showInteractive={false} />
          {menuNode !== undefined && (
            <Panel position={rtl ? 'top-left' : 'top-right'}>
              <NodeMenu
                title={nodeName(t, menuNode.node)}
                onClose={closeMenu}
                items={[
                  ...(menuNode.node.id == null
                    ? []
                    : [
                        {
                          key: 'open',
                          label: t('cmdb.map.open'),
                          to: `/cmdb/${menuNode.node.id}`,
                        },
                      ]),
                  {
                    key: 'expand',
                    label: t('cmdb.map.expand'),
                    disabled: expanded.has(menuNode.key) || menuNode.key === baseKey,
                    onSelect: () => {
                      onExpand(menuNode.key);
                      closeMenu();
                    },
                  },
                  ...(canEdit
                    ? menuEdges
                        .filter((e) => e.from === baseKey || e.to === baseKey)
                        .map((e) => {
                          // Said from the base CI's side, since removal acts on the base's own
                          // links: "runs on X" for a forward link, the inverse name otherwise.
                          const fromBase = e.from === baseKey;
                          const other = byKey.get(fromBase ? e.to : e.from);
                          return {
                            key: `remove-${e.key}`,
                            label: t('cmdb.map.remove_link', {
                              relationship: relationshipName(
                                t,
                                locale,
                                typeOf.get(e.edge.type_id),
                                fromBase ? 'forward' : 'inverse',
                              ),
                              name: other === undefined ? '' : nodeName(t, other.node),
                            }),
                            danger: true,
                            onSelect: () => {
                              closeMenu();
                              askRemove(e);
                            },
                          };
                        })
                    : []),
                ]}
              />
            </Panel>
          )}
        </ReactFlow>
      </div>
      <MapList id={listId} graph={graph} relName={relName} byKey={byKey} />
    </Flex>
  );
}

/** Fit once the nodes have their sizes (the designer's QA V-02 fix, reused). */
function FitWhenReady() {
  const flow = useReactFlow();
  const ready = useNodesInitialized();
  const done = useRef(false);
  useEffect(() => {
    if (!ready || done.current) return;
    done.current = true;
    window.requestAnimationFrame(() => void flow.fitView(FIT));
  }, [ready, flow]);
  return null;
}

interface MenuItem {
  key: string;
  label: string;
  to?: string;
  disabled?: boolean;
  danger?: boolean;
  onSelect?: () => void;
}

/**
 * A node's menu: focus moves into it, Up and Down move through it, Escape closes it (only it:
 * the event goes no further, so a dialog or drawer around the map stays open; condition 6) and
 * focus goes back to the node.
 */
function NodeMenu({
  title,
  items,
  onClose,
}: {
  title: string;
  items: MenuItem[];
  onClose: () => void;
}) {
  const t = useLabel();
  const { token } = theme.useToken();
  const box = useRef<HTMLDivElement>(null);
  const entries = () => [
    ...(box.current?.querySelectorAll<HTMLElement>(
      '[role="menuitem"]:not([aria-disabled="true"])',
    ) ?? []),
  ];
  useEffect(() => {
    entries()[0]?.focus();
  }, []);
  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    const all = entries();
    const at = all.indexOf(document.activeElement as HTMLElement);
    const next =
      event.key === 'ArrowDown' ? (at + 1) % all.length : (at - 1 + all.length) % all.length;
    all[next]?.focus();
  };
  return (
    <div
      ref={box}
      role="menu"
      aria-label={t('cmdb.map.menu', { name: title })}
      onKeyDown={onKeyDown}
      className="nodrag nopan"
      data-testid="ci-map-menu"
      style={{
        minWidth: 200,
        maxWidth: 280,
        padding: 4,
        background: token.colorBgElevated,
        borderRadius: token.borderRadiusLG,
        boxShadow: token.boxShadowSecondary,
      }}
    >
      <Typography.Text strong style={{ display: 'block', padding: '4px 8px' }} ellipsis>
        <bdi>{title}</bdi>
      </Typography.Text>
      {items.map((item) =>
        item.to !== undefined ? (
          <Link
            key={item.key}
            to={item.to}
            role="menuitem"
            style={menuItemStyle(token.colorText)}
            data-testid={`ci-map-menu-${item.key}`}
          >
            {item.label}
          </Link>
        ) : (
          <button
            key={item.key}
            type="button"
            role="menuitem"
            aria-disabled={item.disabled === true}
            onClick={() => {
              if (item.disabled !== true) item.onSelect?.();
            }}
            style={{
              ...menuItemStyle(item.danger === true ? token.colorError : token.colorText),
              opacity: item.disabled === true ? 0.5 : 1,
            }}
            data-testid={`ci-map-menu-${item.key}`}
          >
            <bdi>{item.label}</bdi>
          </button>
        ),
      )}
    </div>
  );
}

const menuItemStyle = (color: string) =>
  ({
    display: 'block',
    width: '100%',
    padding: '6px 8px',
    border: 0,
    background: 'none',
    color,
    textAlign: 'start',
    cursor: 'pointer',
    borderRadius: 4,
  }) as const;

/**
 * One CI on the map: its name, type and state in words, the state as a tone AND an icon and
 * border style (condition 8), the counters once there are counts. A restricted node is neutral,
 * dotted, says "A CI you can't open" and has nothing to click.
 */
const CiNodeView = memo(function CiNodeView({ data }: NodeProps<CiFlowNode>) {
  const t = useLabel();
  const { token } = theme.useToken();
  const { locale } = useAppearance();
  const node = data.shown.node;
  const look = nodeLook(node);
  const stateText = nodeState(t, locale, node);
  const icon = node.restricted ? (
    <LockOutlined />
  ) : node.state_category === 'end_of_life' ? (
    <StopOutlined />
  ) : (
    <CheckCircleOutlined />
  );
  return (
    <div
      data-testid={`ci-map-node-${data.shown.key}`}
      data-restricted={node.restricted ? 'true' : undefined}
      style={{
        width: MAP_NODE_WIDTH,
        minHeight: MAP_NODE_HEIGHT,
        padding: '6px 10px',
        background: token.colorBgContainer,
        border: `${String(data.base ? 2 : 1)}px ${look.border} ${data.base ? token.colorPrimary : token.colorBorder}`,
        borderRadius: token.borderRadiusLG,
      }}
    >
      {/* Edges need ends; the pointer never links here, so they stay out of sight. */}
      <Handle type="target" position={Position.Top} isConnectable={false} style={HIDDEN} />
      <Handle type="source" position={Position.Bottom} isConnectable={false} style={HIDDEN} />
      <Flex vertical gap={2}>
        <Typography.Text strong ellipsis style={{ fontSize: 13 }}>
          <bdi>{data.title}</bdi>
        </Typography.Text>
        <Flex gap={4} align="center" wrap>
          {node.restricted ? (
            <ToneTag tone="default" icon={icon}>
              {t('cmdb.map.restricted_short')}
            </ToneTag>
          ) : (
            <>
              {stateText !== '' && (
                <ToneTag tone={look.tone} icon={icon}>
                  <bdi>{stateText}</bdi>
                </ToneTag>
              )}
              <Typography.Text type="secondary" ellipsis style={{ fontSize: 12 }}>
                <bdi>{nodeType(t, locale, node)}</bdi>
              </Typography.Text>
            </>
          )}
        </Flex>
        {data.counts !== null && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }} data-testid="ci-map-counts">
            {t('cmdb.map.counts', {
              incident: data.counts.incident,
              problem: data.counts.problem,
              change: data.counts.change,
            })}
          </Typography.Text>
        )}
      </Flex>
    </div>
  );
});

const HIDDEN = { opacity: 0, pointerEvents: 'none', left: '50%', top: '50%' } as const;
const NODE_TYPES = { ci: CiNodeView };

/** The map as a list (condition 6's non-visual equivalent): every node and its links in words. */
function MapList({
  id,
  graph,
  relName,
  byKey,
}: {
  id: string;
  graph: MapGraph;
  relName: (e: ShownEdge) => string;
  byKey: ReadonlyMap<string, ShownNode>;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  return (
    <section id={id} tabIndex={-1} aria-label={t('cmdb.map.as_list')} data-testid="ci-map-list">
      <Typography.Title level={5}>{t('cmdb.map.as_list')}</Typography.Title>
      <List
        size="small"
        dataSource={graph.nodes}
        renderItem={(n) => {
          const out = graph.edges.filter((e) => e.from === n.key);
          return (
            <List.Item data-testid={`ci-map-list-${n.key}`}>
              <Flex vertical gap={2}>
                <Typography.Text strong>
                  {n.node.restricted || n.node.id == null ? (
                    t('cmdb.map.restricted')
                  ) : (
                    <Link to={`/cmdb/${n.node.id}`}>
                      <bdi>{n.node.name}</bdi>
                    </Link>
                  )}
                </Typography.Text>
                {!n.node.restricted && (
                  <Typography.Text type="secondary">
                    <bdi>{nodeType(t, locale, n.node)}</bdi> ·{' '}
                    <bdi>{nodeState(t, locale, n.node)}</bdi>
                  </Typography.Text>
                )}
                {out.map((e) => {
                  const to = byKey.get(e.to);
                  return (
                    <Typography.Text key={e.key}>
                      <bdi>{relName(e)}</bdi>{' '}
                      <bdi>{to === undefined ? '' : nodeName(t, to.node)}</bdi>
                    </Typography.Text>
                  );
                })}
              </Flex>
            </List.Item>
          );
        }}
      />
    </section>
  );
}

function saveText(name: string, text: string, type: string) {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name.replace(/[^\p{L}\p{N}_.-]+/gu, '-');
  link.click();
  URL.revokeObjectURL(url);
}
