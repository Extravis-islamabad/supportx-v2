import { PlusOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Input, Select, Space, Table } from 'antd';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  problemKeys,
  useProblemCatalogue,
  useProblems,
  useProblemViews,
} from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import {
  CellText,
  EmptyText,
  FilterBar,
  ListPage,
  PageHeader,
  reportError,
  useAccess,
  useColumnWidths,
  useDateTime,
  useLabel,
} from '@supportx/ui';

import { searchOf } from '../incidents/searchOf';
import { PriorityTag, StatusTag } from '../incidents/tags';
import { SEARCH_DELAY_MS, useDebounced } from '../../useDebounced';
import { RepeatedIncidents } from './RepeatedIncidents';

/**
 * Problems (WP-044a s5, WP-044c S1): the list, live on the problems list channel (§8), with
 * "New problem" for those who may create one. The built-in views with their counts (known errors
 * and accepted ones due for review among them), and one search box for subject words or a
 * display ID (PRB-7), across problems and known errors alike (both are problems). The subject
 * ends in an ellipsis and the ID and subject stay in view when the table scrolls sideways.
 */
const SUBJECT_MIN = 180; // the subject stays readable however narrow it is dragged
const OWN_WIDTHS = { id: 130, subject: 320, status: 150, priority: 130, owner: 180, updated: 170 };

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
  // Each person's column widths, per view (Haider, 2026-11-10): drag or arrow keys on a header.
  const titles: Record<string, string> = {
    id: t('incidents.col.id'),
    subject: t('work_item.field.subject'),
    status: t('work_item.field.status'),
    priority: t('work_item.field.priority'),
    owner: t('problems.owner'),
    updated: t('incidents.col.updated'),
  };
  const widths = useColumnWidths({
    kind: 'problems',
    viewKey: view ?? views.data?.[0]?.view ?? 'all',
    // Not before the views load: a resize then would land on another view's settings.
    enabled: view !== undefined || views.data !== undefined,
    keys: Object.keys(titles),
    defaults: OWN_WIDTHS,
    minWidths: { subject: SUBJECT_MIN },
    label: (key) => t('layout.resize_column', { column: titles[key] ?? '' }),
  });
  useListChannel('problems', () => {
    void queryClient.invalidateQueries({ queryKey: [...problemKeys.all, 'list'] });
    void queryClient.invalidateQueries({ queryKey: problemKeys.views });
  });
  if (list.error) reportError(list.error);
  const create = can('problems.create');
  const rows = list.data?.items ?? [];
  const people = list.data?.people ?? {};
  return (
    // The list template (D-124, Haider 2026-11-10): ListPage spaces it; one FilterBar.
    <ListPage
      testId="prb-page"
      header={
        <PageHeader
          title={t('nav.problems')}
          extra={
            <Space wrap>
              <Button
                onClick={() => void navigate('/problems/known-errors')}
                data-testid="prb-kedb"
              >
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
      }
      kpis={<RepeatedIncidents enabled={create} />}
      filters={
        <FilterBar
          testId="prb-filterbar"
          view={
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
          }
          search={
            <Input.Search
              allowClear
              placeholder={t('problems.search')}
              aria-label={t('problems.search')}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
              }}
              data-testid="prb-search"
            />
          }
          extra={
            widths.changed ? (
              <Button onClick={widths.reset} data-testid="prb-reset-widths">
                {t('layout.reset_widths')}
              </Button>
            ) : undefined
          }
        />
      }
    >
      <Table
        rowKey="id"
        loading={list.isLoading}
        scroll={{ x: 960 }}
        dataSource={rows}
        pagination={false}
        data-testid="prb-list"
        components={widths.components}
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
            width: widths.width('id'),
            onHeaderCell: () => widths.header('id'),
            fixed: 'left' as const,
            render: (_, row) => (
              <Link to={`/problems/${row.id}`} data-testid={`prb-row-${row.display_id}`}>
                <strong dir="ltr">{row.display_id}</strong>
              </Link>
            ),
          },
          {
            key: 'subject',
            title: t('work_item.field.subject'),
            width: widths.width('subject'),
            onHeaderCell: () => widths.header('subject'),
            fixed: 'left' as const,
            // Cut with an ellipsis; the whole subject is the cell's tooltip.
            ellipsis: true,
            render: (_, row) => <CellText title={row.subject}>{row.subject}</CellText>,
          },
          {
            key: 'status',
            title: t('work_item.field.status'),
            width: widths.width('status'),
            onHeaderCell: () => widths.header('status'),
            render: (_, row) => <StatusTag status={row.status} catalogue={catalogue.data} />,
          },
          {
            key: 'priority',
            title: t('work_item.field.priority'),
            width: widths.width('priority'),
            onHeaderCell: () => widths.header('priority'),
            render: (_, row) => (
              <PriorityTag priority={row.priority} source={row.priority_source} />
            ),
          },
          {
            key: 'owner',
            title: t('problems.owner'),
            width: widths.width('owner'),
            onHeaderCell: () => widths.header('owner'),
            ellipsis: true,
            render: (_, row) => (
              <CellText>
                {row.technician_id === null ? '' : (people[row.technician_id]?.display_name ?? '')}
              </CellText>
            ),
          },
          {
            key: 'updated',
            title: t('incidents.col.updated'),
            width: widths.width('updated'),
            onHeaderCell: () => widths.header('updated'),
            render: (_, row) => format(row.updated_at),
          },
        ]}
      />
    </ListPage>
  );
}
