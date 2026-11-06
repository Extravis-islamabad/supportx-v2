import { PlusOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Flex, Input, Select, Space, Table } from 'antd';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  problemKeys,
  useProblemCatalogue,
  useProblems,
  useProblemViews,
} from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import { EmptyText, PageHeader, reportError, useAccess, useDateTime, useLabel } from '@supportx/ui';

import { searchOf } from '../incidents/searchOf';
import { PriorityTag, StatusTag } from '../incidents/tags';
import { SEARCH_DELAY_MS, useDebounced } from '../../useDebounced';

/**
 * Problems (WP-044a s5, WP-044c S1): the list, live on the problems list channel (§8), with
 * "New problem" for those who may create one. The built-in views with their counts (known errors
 * and accepted ones due for review among them), and one search box for subject words or a
 * display ID (PRB-7), across problems and known errors alike (both are problems). The subject
 * ends in an ellipsis and the ID and subject stay in view when the table scrolls sideways.
 */
export function ProblemsPage() {
  const t = useLabel();
  const { format } = useDateTime();
  const { can } = useAccess();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [view, setView] = useState<string | undefined>();
  const [search, setSearch] = useState('');
  const text = useDebounced(search.trim(), SEARCH_DELAY_MS);
  const views = useProblemViews();
  const list = useProblems({ view, filter: searchOf(text) });
  const catalogue = useProblemCatalogue();
  useListChannel('problems', () => {
    void queryClient.invalidateQueries({ queryKey: [...problemKeys.all, 'list'] });
    void queryClient.invalidateQueries({ queryKey: problemKeys.views });
  });
  if (list.error) reportError(list.error);
  const create = can('problems.create');
  const rows = list.data?.items ?? [];
  const people = list.data?.people ?? {};
  return (
    <Flex vertical gap={16} style={{ width: '100%' }}>
      <PageHeader
        title={t('nav.problems')}
        extra={
          <Space wrap>
            <Button onClick={() => void navigate('/problems/known-errors')} data-testid="prb-kedb">
              {t('problems.known_error.database')}
            </Button>
            {create && (
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => void navigate('/problems/new')}
                data-testid="prb-new"
              >
                {t('problems.new')}
              </Button>
            )}
          </Space>
        }
      />
      <Flex gap={8} wrap>
        <Select
          style={{ minWidth: 260 }}
          prefix={`${t('incidents.view')}:`}
          aria-label={t('incidents.view')}
          value={view ?? views.data?.[0]?.view}
          onChange={setView}
          loading={views.isLoading}
          options={(views.data ?? []).map((v) => ({
            value: v.view,
            label: `${t(`work_item_view.${v.view}`)} (${String(v.count)}${v.capped ? '+' : ''})`,
          }))}
          data-testid="prb-view"
        />
        <Input.Search
          allowClear
          style={{ flex: '1 1 260px', maxWidth: 420 }}
          placeholder={t('problems.search')}
          aria-label={t('problems.search')}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
          }}
          data-testid="prb-search"
        />
      </Flex>
      <Table
        rowKey="id"
        loading={list.isLoading}
        scroll={{ x: 960 }}
        dataSource={rows}
        pagination={false}
        data-testid="prb-list"
        locale={{
          emptyText: list.isLoading ? (
            <span />
          ) : (
            // The same plain empty text as incidents and releases (QA6-PRB-04).
            <span data-testid="prb-empty">
              <EmptyText>{t(text === '' ? 'problems.empty' : 'problems.no_match')}</EmptyText>
            </span>
          ),
        }}
        columns={[
          {
            key: 'id',
            title: t('incidents.col.id'),
            width: 130,
            fixed: 'left' as const,
            render: (_, row) => (
              <Link to={`/problems/${row.id}`} data-testid={`prb-row-${row.display_id}`}>
                <strong dir="ltr">{row.display_id}</strong>
              </Link>
            ),
          },
          {
            key: 'subject',
            title: t('incidents.col.subject'),
            width: 320,
            fixed: 'left' as const,
            // Cut with an ellipsis; the whole subject is the cell's tooltip.
            ellipsis: true,
            render: (_, row) => (
              <bdi dir="auto" title={row.subject}>
                {row.subject}
              </bdi>
            ),
          },
          {
            key: 'status',
            title: t('incidents.col.status'),
            width: 150,
            render: (_, row) => <StatusTag status={row.status} catalogue={catalogue.data} />,
          },
          {
            key: 'priority',
            title: t('incidents.col.priority'),
            width: 130,
            render: (_, row) => (
              <PriorityTag priority={row.priority} source={row.priority_source} />
            ),
          },
          {
            key: 'owner',
            title: t('problems.owner'),
            width: 180,
            ellipsis: true,
            render: (_, row) =>
              row.technician_id === null ? '' : (people[row.technician_id]?.display_name ?? ''),
          },
          {
            key: 'updated',
            title: t('incidents.col.updated'),
            width: 170,
            render: (_, row) => format(row.updated_at),
          },
        ]}
      />
    </Flex>
  );
}
