import { useQueryClient } from '@tanstack/react-query';
import { Button, Card, Col, Empty, Flex, Input, Row, Segmented, Table, Typography } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import { queryKeys, useBusinessViews, type BusinessViewListItem } from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  FilterBar,
  ListPage,
  NoAccess,
  NotInPlan,
  PageHeader,
  useAccess,
  useDateTime,
  useLabel,
  useLicence,
  useMinWidth,
} from '@supportx/ui';

import { SEARCH_DELAY_MS, useDebounced } from '../../../useDebounced';

type Shape = 'list' | 'cards';

/**
 * Business views (template C; REQ-CMDB-009): every saved map whose base CI you may see, as a
 * list or as cards (cards by default on a phone). Live: a view saved, renamed or removed
 * anywhere refetches the list ("views changed", no names).
 */
export function BusinessViewsPage() {
  const t = useLabel();
  const { can } = useAccess();
  const { has, isAdmin } = useLicence();
  const dates = useDateTime();
  const wide = useMinWidth(768);
  const queryClient = useQueryClient();
  const [shape, setShape] = useState<Shape | null>(null);
  const [search, setSearch] = useState('');
  const typed = useDebounced(search, SEARCH_DELAY_MS);
  const allowed = has('cmdb') && can('cmdb.view');
  const views = useBusinessViews({ search: allowed ? typed : '' });
  useTenantChannel((message) => {
    if (message.type === 'cmdb.views_changed' || message.type === 'refresh') {
      void queryClient.invalidateQueries({ queryKey: [...queryKeys.cmdb.views, 'list'] });
    }
  });
  if (!has('cmdb')) return <NotInPlan titleKey="cmdb.views.title" isAdmin={isAdmin} />;
  if (!can('cmdb.view')) return <NoAccess titleKey="cmdb.views.title" />;
  const items = views.data?.pages.flatMap((p) => p.items) ?? [];
  const shown: Shape = shape ?? (wide ? 'list' : 'cards');
  const total = views.data?.pages[0]?.estimated_total;
  const empty = (
    <Empty
      description={t(typed === '' ? 'cmdb.views.empty' : 'cmdb.views.none_found')}
      data-testid="cmdb-views-empty"
    />
  );

  return (
    <ListPage
      testId="cmdb-views"
      header={
        <PageHeader
          title={t('cmdb.views.title')}
          count={total == null ? undefined : String(total)}
          description={t('cmdb.views.description')}
        />
      }
      filters={
        <FilterBar
          search={
            <Input.Search
              allowClear
              aria-label={t('cmdb.views.search')}
              placeholder={t('cmdb.views.search')}
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
              }}
              data-testid="cmdb-views-search"
            />
          }
          extra={
            <Segmented<Shape>
              value={shown}
              onChange={setShape}
              options={[
                { value: 'list', label: t('cmdb.views.as_list') },
                { value: 'cards', label: t('cmdb.views.as_cards') },
              ]}
              data-testid="cmdb-views-shape"
            />
          }
        />
      }
    >
      {shown === 'list' ? (
        <div
          role="region"
          aria-label={t('cmdb.views.title')}
          tabIndex={0}
          style={{ overflowX: 'auto' }}
        >
          <Table<BusinessViewListItem>
            rowKey="id"
            size="small"
            loading={views.isPending}
            dataSource={items}
            pagination={false}
            locale={{ emptyText: views.isPending ? ' ' : empty }}
            data-testid="cmdb-views-table"
            columns={[
              {
                key: 'name',
                title: t('cmdb.field.name'),
                render: (_, row) => (
                  <Flex vertical>
                    <Link to={`/cmdb/views/${row.id}`} data-testid={`cmdb-view-${row.id}`}>
                      <bdi>{row.name}</bdi>
                    </Link>
                    {row.description !== null && (
                      <Typography.Text type="secondary" ellipsis style={{ maxWidth: 480 }}>
                        <bdi>{row.description}</bdi>
                      </Typography.Text>
                    )}
                  </Flex>
                ),
              },
              {
                key: 'base',
                title: t('cmdb.views.base_ci'),
                render: (_, row) => <BaseCi row={row} />,
              },
              {
                key: 'layout',
                title: t('cmdb.field.layout'),
                render: (_, row) => t(`cmdb_view_layout.${row.layout}`),
              },
              {
                key: 'updated',
                title: t('cmdb.field.updated_at'),
                render: (_, row) => <bdi>{dates.format(row.updated_at)}</bdi>,
              },
            ]}
          />
        </div>
      ) : items.length === 0 && !views.isPending ? (
        empty
      ) : (
        <Row gutter={[12, 12]} data-testid="cmdb-views-cards">
          {items.map((row) => (
            <Col key={row.id} xs={24} sm={12} lg={8}>
              <Card size="small" title={<bdi>{row.name}</bdi>}>
                <Flex vertical gap={4}>
                  {row.description !== null && (
                    <Typography.Paragraph
                      type="secondary"
                      ellipsis={{ rows: 2 }}
                      style={{ margin: 0 }}
                    >
                      <bdi>{row.description}</bdi>
                    </Typography.Paragraph>
                  )}
                  <Typography.Text>
                    {t('cmdb.views.base_ci')}: <BaseCi row={row} />
                  </Typography.Text>
                  <Typography.Text type="secondary">
                    {t(`cmdb_view_layout.${row.layout}`)} ·{' '}
                    <bdi>{dates.format(row.updated_at)}</bdi>
                  </Typography.Text>
                  <Link to={`/cmdb/views/${row.id}`} data-testid={`cmdb-view-card-${row.id}`}>
                    {t('cmdb.views.open')}
                  </Link>
                </Flex>
              </Card>
            </Col>
          ))}
        </Row>
      )}
      {views.hasNextPage && (
        <Button loading={views.isFetchingNextPage} onClick={() => void views.fetchNextPage()}>
          {t('cmdb.more')}
        </Button>
      )}
    </ListPage>
  );
}

/** A view's base CI: its display ID and name, a link to the CI (CMDB polish). */
function BaseCi({ row }: { row: BusinessViewListItem }) {
  const base = row.base_ci;
  if (base == null) return null;
  return (
    <Link to={`/cmdb/${base.id}`} data-testid={`cmdb-view-base-${row.id}`}>
      <bdi>
        {base.display_id} · {base.name}
      </bdi>
    </Link>
  );
}
