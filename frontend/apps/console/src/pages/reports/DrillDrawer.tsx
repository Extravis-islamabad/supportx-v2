import { Drawer, List, Space, Typography } from 'antd';
import { Link } from 'react-router';

import {
  useAssetRecords,
  useChanges,
  useIncidentCatalogue,
  useIncidents,
  useProblems,
  useReleases,
  useServiceRequests,
  type FilterExpression,
} from '@supportx/api-client';
import { useLabels } from '@supportx/labels';

import { StatusTag } from '../incidents/tags';

export interface Drill {
  title: string;
  /** The list filter behind the number clicked (REQ-RPT-037). */
  filter: unknown;
  count: number | null;
  /** The list the report's entity drills to (`list_path`, e.g. "changes"); incidents if unset. */
  listPath?: string;
}

const PAGE = 50;

/**
 * The records behind a number, beside the report so the user keeps their place (REQ-DSH-024).
 * It is the incident list itself with the row's filter: same scope, same count.
 */
export function DrillDrawer({ drill, onClose }: { drill: Drill | null; onClose: () => void }) {
  // Each work item type drills to its own list (WP-045d S4c for changes; WP-058b S5b for
  // releases, problems and requests): the same scope and count as the chart.
  const own = drill?.listPath === undefined ? undefined : LISTS[drill.listPath];
  if (drill !== null && own !== undefined) {
    return <RecordDrill drill={drill} onClose={onClose} useRows={own.useRows} route={own.route} />;
  }
  return <IncidentDrill drill={drill} onClose={onClose} />;
}

interface DrillRows {
  rows: readonly { id: string; display_id: string; subject: string; status: string }[];
  total: number | null;
  pending: boolean;
  /** The list cannot take this chart's filter (yet): say so, never a failed request. */
  unavailable?: boolean;
}

/** Whether a filter tree names one of `fields` anywhere. */
function mentions(tree: unknown, fields: ReadonlySet<string>): boolean {
  if (tree === null || typeof tree !== 'object') return false;
  if (Array.isArray(tree)) return tree.some((t) => mentions(t, fields));
  const node = tree as Record<string, unknown>;
  if (typeof node.field === 'string' && fields.has(node.field)) return true;
  return Object.values(node).some((v) => mentions(v, fields));
}

// The asset report's money buckets (assets.view_financials): the asset list does not take them
// as filters yet (lane B adds them), so their bars do not list (lane B's #S5b note).
const ASSET_MONEY = new Set(['book_value', 'total_cost', 'purchase_price', 'purchase_tax']);

function useChangeRows(filter: unknown): DrillRows {
  const list = useChanges({
    filter: filter == null ? undefined : JSON.stringify(filter),
    include_total: true,
  });
  return {
    rows: list.data?.items ?? [],
    total: list.data?.estimated_total ?? null,
    pending: list.isPending,
  };
}

function useReleaseRows(filter: unknown): DrillRows {
  const list = useReleases({
    filter: filter == null ? undefined : JSON.stringify(filter),
    include_total: true,
  });
  return {
    rows: list.data?.items ?? [],
    total: list.data?.estimated_total ?? null,
    pending: list.isPending,
  };
}

function useProblemRows(filter: unknown): DrillRows {
  const list = useProblems({ filter: (filter ?? undefined) as FilterExpression | undefined });
  return {
    rows: list.data?.items ?? [],
    total: list.data?.estimated_total ?? null,
    pending: list.isPending,
  };
}

function useRequestRows(filter: unknown): DrillRows {
  const list = useServiceRequests({
    filter: (filter ?? undefined) as FilterExpression | undefined,
  });
  return {
    rows: list.data?.items ?? [],
    total: list.data?.estimated_total ?? null,
    pending: list.isPending,
  };
}

function useAssetRows(filter: unknown): DrillRows {
  // Lane B's asset list takes the report's filter as its list API does (FilterExpression JSON),
  // over every asset (view "all"), as the report counted them (the trash left out).
  const unavailable = mentions(filter, ASSET_MONEY);
  const list = useAssetRecords(
    { view: 'all', filter: filter == null ? undefined : JSON.stringify(filter) },
    !unavailable,
  );
  const first = list.data?.pages[0];
  return {
    rows: (list.data?.pages.flatMap((page) => page.items) ?? []).map((asset) => ({
      id: asset.id,
      display_id: asset.tag ?? '',
      subject: asset.name,
      status: '',
    })),
    total: first?.estimated_total ?? null,
    pending: !unavailable && list.isPending,
    unavailable,
  };
}

/** A report's `list_path` → its list's rows and where a row opens. Incidents are the default. */
const LISTS: Record<string, { useRows: (filter: unknown) => DrillRows; route: string }> = {
  changes: { useRows: useChangeRows, route: 'changes' },
  releases: { useRows: useReleaseRows, route: 'releases' },
  problems: { useRows: useProblemRows, route: 'problems' },
  'service-requests': { useRows: useRequestRows, route: 'requests' },
  assets: { useRows: useAssetRows, route: 'assets' },
};

/** A type's own list with the row's filter: same scope, same count as the chart. */
function RecordDrill({
  drill,
  onClose,
  useRows,
  route,
}: {
  drill: Drill;
  onClose: () => void;
  useRows: (filter: unknown) => DrillRows;
  route: string;
}) {
  const t = useLabels();
  const { rows, total, pending, unavailable = false } = useRows(drill.filter);
  return (
    <Drawer
      open
      onClose={onClose}
      title={drill.title}
      width={560}
      destroyOnHidden
      data-testid="report-drill"
    >
      {unavailable ? (
        <Typography.Text type="secondary" data-testid="report-drill-unavailable">
          {t('reports.drill_unavailable')}
        </Typography.Text>
      ) : (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Text type="secondary" data-testid="report-drill-count">
            {t('reports.drill_count', { count: total ?? rows.length })}
          </Typography.Text>
          <List
            loading={pending}
            dataSource={[...rows]}
            renderItem={(item) => (
              <List.Item>
                <Space direction="vertical" size={0} style={{ minWidth: 0 }}>
                  <Link to={`/${route}/${item.id}`}>
                    <bdi>{item.display_id}</bdi> {item.subject}
                  </Link>
                  {item.status !== '' && (
                    <Typography.Text type="secondary">
                      {t(`work_item_status.${item.status}`)}
                    </Typography.Text>
                  )}
                </Space>
              </List.Item>
            )}
          />
        </Space>
      )}
    </Drawer>
  );
}

function IncidentDrill({ drill, onClose }: { drill: Drill | null; onClose: () => void }) {
  const t = useLabels();
  const catalogue = useIncidentCatalogue(drill !== null);
  const list = useIncidents(
    {
      filter: (drill?.filter ?? undefined) as FilterExpression | undefined,
      limit: PAGE,
      sort: '-updated_at',
    },
    drill !== null,
  );
  const first = list.data?.pages[0];
  const rows = list.data?.pages.flatMap((page) => page.items) ?? [];
  const total = first?.estimated_total ?? null;

  return (
    <Drawer
      open={drill !== null}
      onClose={onClose}
      title={drill?.title}
      width={560}
      destroyOnHidden
      data-testid="report-drill"
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        <Typography.Text type="secondary" data-testid="report-drill-count">
          {t('reports.drill_count', { count: total ?? rows.length })}
        </Typography.Text>
        <List
          loading={list.isPending}
          dataSource={rows}
          renderItem={(item) => (
            <List.Item>
              <Space direction="vertical" size={0} style={{ minWidth: 0 }}>
                <Link to={`/incidents/${item.id}`}>
                  <bdi>{item.display_id}</bdi> {item.subject}
                </Link>
                <StatusTag status={item.status} catalogue={catalogue.data} />
              </Space>
            </List.Item>
          )}
        />
        {list.hasNextPage && (
          <Typography.Link
            onClick={() => void list.fetchNextPage()}
            data-testid="report-drill-more"
          >
            {t('reports.show_more')}
          </Typography.Link>
        )}
      </Space>
    </Drawer>
  );
}
