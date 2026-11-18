import {
  Flex,
  Result,
  Segmented,
  Select,
  Skeleton,
  Space,
  Switch,
  TreeSelect,
  Typography,
} from 'antd';
import { useMemo, useState, type ReactNode } from 'react';

import {
  useCiTypes,
  useRelationshipTypes,
  type BusinessViewFilters,
  type NeighboursQuery,
} from '@supportx/api-client';
import { CI_MAP_LAYOUTS, ReactFlowProvider, type CiMapLayout, type MapPoint } from '@supportx/flow';
import { useAppearance, useLabel } from '@supportx/ui';

import { nameOf, typeTree } from '../names';
import { CiMap } from './CiMap';
import { DEFAULT_FILTERS, type MapSettings } from './positions';
import { useMapGraph } from './useMapGraph';
import { relationshipTypeName } from './words';

export interface MapWorkspaceProps {
  baseId: string;
  fileName: string;
  canEdit: boolean;
  /** A business view's saved layout, filters and pinned positions. */
  initial?: MapSettings & { positions: ReadonlyMap<string, MapPoint> };
  /** The current settings, whenever they change (a business view saves them). */
  onSettings?: (settings: MapSettings) => void;
  onPositions?: (positions: ReadonlyMap<string, MapPoint>) => void;
  /** Buttons beside the filters (add a relationship, save as a business view…). */
  actions?: ReactNode;
  testId?: string;
}

const DEPTHS = [1, 2, 3] as const;

/**
 * The map with its controls (REQ-CMDB-008): layout, depth, relationship type, CI type and
 * end-of-life filters, then the map itself. Used by the CI's Map tab and by a business view.
 */
export function MapWorkspace(props: MapWorkspaceProps) {
  const t = useLabel();
  const { locale } = useAppearance();
  const [layout, setLayout] = useState<CiMapLayout>(props.initial?.layout ?? 'radial');
  const [filters, setFilters] = useState<BusinessViewFilters>(
    props.initial?.filters ?? DEFAULT_FILTERS,
  );
  const [expanded, setExpanded] = useState<string[]>([]);
  const types = useRelationshipTypes();
  const ciTypes = useCiTypes();
  const query: NeighboursQuery = useMemo(
    () => ({
      depth: filters.depth,
      types: filters.relationship_type_ids ?? [],
      ciTypes: filters.ci_type_ids ?? [],
      eol: filters.show_eol,
    }),
    [filters],
  );
  const graph = useMapGraph(props.baseId, expanded, query);
  const tree = useMemo(
    () => typeTree(ciTypes.data?.items ?? [], (x) => nameOf(t, locale, x, 'cmdb_ci_type')),
    [ciTypes.data, t, locale],
  );
  const change = (next: { layout?: CiMapLayout; filters?: BusinessViewFilters }) => {
    const settings = { layout: next.layout ?? layout, filters: next.filters ?? filters };
    if (next.layout !== undefined) setLayout(next.layout);
    if (next.filters !== undefined) setFilters(next.filters);
    props.onSettings?.(settings);
  };
  const expandedSet = useMemo(() => new Set(expanded), [expanded]);

  return (
    <Flex vertical gap={12} data-testid={props.testId ?? 'ci-map-workspace'}>
      <Flex gap={12} wrap align="end">
        <Labelled label={t('cmdb.field.layout')}>
          <Segmented<CiMapLayout>
            value={layout}
            onChange={(value) => {
              change({ layout: value });
            }}
            options={CI_MAP_LAYOUTS.map((value) => ({
              value,
              label: t(`cmdb_view_layout.${value}`),
            }))}
            data-testid="ci-map-layout"
          />
        </Labelled>
        <Labelled label={t('cmdb.map.depth')}>
          <Select<number>
            aria-label={t('cmdb.map.depth')}
            value={filters.depth}
            onChange={(depth) => {
              change({ filters: { ...filters, depth } });
            }}
            options={DEPTHS.map((value) => ({
              value,
              label: t('cmdb.map.depth_value', { count: value }),
            }))}
            style={{ width: 140 }}
            data-testid="ci-map-depth"
          />
        </Labelled>
        <Labelled label={t('cmdb.map.filter_relationships')}>
          <Select<string[]>
            mode="multiple"
            allowClear
            aria-label={t('cmdb.map.filter_relationships')}
            placeholder={t('cmdb.map.all_relationships')}
            value={filters.relationship_type_ids ?? []}
            onChange={(ids) => {
              change({ filters: { ...filters, relationship_type_ids: ids } });
            }}
            options={(types.data?.items ?? []).map((x) => ({
              value: x.id,
              label: relationshipTypeName(t, locale, x),
            }))}
            optionFilterProp="label"
            maxTagCount="responsive"
            style={{ minWidth: 200, maxWidth: 320 }}
            data-testid="ci-map-filter-types"
          />
        </Labelled>
        <Labelled label={t('cmdb.map.filter_ci_types')}>
          <TreeSelect<string[]>
            multiple
            allowClear
            treeDefaultExpandAll
            aria-label={t('cmdb.map.filter_ci_types')}
            placeholder={t('cmdb.all_types')}
            value={filters.ci_type_ids ?? []}
            onChange={(ids) => {
              change({ filters: { ...filters, ci_type_ids: ids } });
            }}
            treeData={tree}
            maxTagCount="responsive"
            style={{ minWidth: 200, maxWidth: 320 }}
            data-testid="ci-map-filter-ci-types"
          />
        </Labelled>
        <Space>
          <Switch
            aria-label={t('cmdb.map.show_eol')}
            checked={filters.show_eol}
            onChange={(on) => {
              change({ filters: { ...filters, show_eol: on } });
            }}
            data-testid="ci-map-eol"
          />
          {t('cmdb.map.show_eol')}
        </Space>
        {props.actions !== undefined && (
          <Space wrap style={{ marginInlineStart: 'auto' }}>
            {props.actions}
          </Space>
        )}
      </Flex>
      {graph.loading ? (
        <Skeleton active data-testid="ci-map-loading" />
      ) : graph.error !== null && graph.nodes.length === 0 ? (
        <Result status="warning" title={t('cmdb.map.not_loaded')} />
      ) : (
        <ReactFlowProvider>
          <CiMap
            baseKey={props.baseId}
            graph={graph}
            types={types.data?.items ?? []}
            layout={layout}
            pinned={props.initial?.positions}
            expanded={expandedSet}
            onExpand={(key) => {
              setExpanded((before) => (before.includes(key) ? before : [...before, key]));
            }}
            canEdit={props.canEdit}
            onPositions={props.onPositions}
            fileName={props.fileName}
          />
        </ReactFlowProvider>
      )}
    </Flex>
  );
}

function Labelled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Flex vertical gap={4}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {label}
      </Typography.Text>
      {children}
    </Flex>
  );
}
