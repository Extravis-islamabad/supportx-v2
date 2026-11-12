import { Drawer, List, Space, Typography } from 'antd';
import { Link } from 'react-router';

import {
  useChanges,
  useIncidentCatalogue,
  useIncidents,
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
  // A change report drills to the change list (WP-045d S4c, REQ-CHG-116 AC2).
  if (drill?.listPath === 'changes') return <ChangeDrill drill={drill} onClose={onClose} />;
  return <IncidentDrill drill={drill} onClose={onClose} />;
}

/** The change list with the row's filter: same scope, same count as the chart. */
function ChangeDrill({ drill, onClose }: { drill: Drill; onClose: () => void }) {
  const t = useLabels();
  const list = useChanges({
    filter: drill.filter == null ? undefined : JSON.stringify(drill.filter),
    include_total: true,
  });
  const rows = list.data?.items ?? [];
  const total = list.data?.estimated_total ?? null;
  return (
    <Drawer
      open
      onClose={onClose}
      title={drill.title}
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
                <Link to={`/changes/${item.id}`}>
                  <bdi>{item.display_id}</bdi> {item.subject}
                </Link>
                <Typography.Text type="secondary">
                  {t(`work_item_status.${item.status}`)}
                </Typography.Text>
              </Space>
            </List.Item>
          )}
        />
      </Space>
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
