import { Button, Card, Flex, List, Spin, Typography } from 'antd';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router';

import { useIncidents, type DashboardFilters, type DashboardWidget } from '@supportx/api-client';
import { useLabels } from '@supportx/labels';

import { PriorityTag } from '../incidents/tags';
import type { Drill } from '../reports/DrillDrawer';
import { widgetTitle } from './layout';
import { recordsQuery } from './widgetDefinition';

/**
 * A records widget (D-114): the newest few records of a list ("overdue", "my open work",
 * "recently updated"), read through the entity's own list in the viewer's scope, so it shows
 * only what they may see and updates live with the list (realtime patches it).
 */
export function RecordsWidget({
  widget,
  userId,
  filters,
  onDrill,
  toolbar,
  dragHandle = false,
}: {
  widget: DashboardWidget;
  userId: string;
  filters: DashboardFilters;
  onDrill: (drill: Drill) => void;
  toolbar?: ReactNode;
  dragHandle?: boolean;
}) {
  const t = useLabels();
  const navigate = useNavigate();
  const records = widget.records;
  const supported = records?.entity === 'incident';
  const query = records ? recordsQuery(records, { userId, filters }) : {};
  const list = useIncidents(query, supported && userId !== '');
  const page = list.data?.pages[0];
  const items = page?.items.slice(0, query.limit) ?? [];
  const title = widgetTitle(widget, t);

  const body = !supported ? (
    <Typography.Text type="secondary">{t('dashboards.widget_unavailable')}</Typography.Text>
  ) : page === undefined ? (
    list.isError ? (
      <Typography.Text type="secondary">{t('dashboards.widget_failed')}</Typography.Text>
    ) : (
      <Spin />
    )
  ) : items.length === 0 ? (
    <Typography.Text type="secondary">{t('dashboards.records_empty')}</Typography.Text>
  ) : (
    <List
      size="small"
      dataSource={items}
      renderItem={(item) => (
        <List.Item
          key={item.id}
          style={{ cursor: 'pointer', paddingInline: 0 }}
          onClick={() => void navigate(`/incidents/${item.id}`)}
          data-testid={`widget-record-${item.display_id}`}
        >
          <Flex gap={8} align="center" style={{ minWidth: 0, width: '100%' }}>
            <Typography.Text type="secondary" style={{ flex: 'none' }}>
              {item.display_id}
            </Typography.Text>
            <Typography.Link ellipsis style={{ flex: 1, minWidth: 0 }}>
              {item.subject}
            </Typography.Link>
            <PriorityTag priority={item.priority} source={item.priority_source} />
          </Flex>
        </List.Item>
      )}
    />
  );

  return (
    <Card
      size="small"
      title={
        <span
          className={dragHandle ? 'dashboard-drag-handle' : undefined}
          style={dragHandle ? { cursor: 'move' } : undefined}
          data-testid={`widget-title-${widget.id}`}
        >
          {title}
        </span>
      }
      style={{ height: '100%', overflow: 'hidden' }}
      styles={{ body: { overflow: 'auto', height: 'calc(100% - 40px)' } }}
      data-testid={`widget-${widget.id}`}
      extra={
        toolbar ??
        (supported && (
          <Button
            size="small"
            type="link"
            onClick={() => {
              onDrill({ title, filter: query.filter ?? null, count: null });
            }}
            data-testid={`widget-open-list-${widget.id}`}
          >
            {t('dashboards.records_open_list')}
          </Button>
        ))
      }
    >
      {body}
    </Card>
  );
}
