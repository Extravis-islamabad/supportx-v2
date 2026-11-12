import { PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Flex, Input, Select, Space, Table, Tag } from 'antd';
import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  releaseKeys,
  useReleaseSettings,
  useReleases,
  type ReleaseListItem,
} from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import {
  CellText,
  loadedEmpty,
  FilterBar,
  ListPage,
  PageHeader,
  usePageCrumbs,
  ToneTag,
  WriteButton,
  reportError,
  useAccess,
  useDateTime,
  useLabel,
  useColumnWidths,
} from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { StatusTag } from '../incidents/tags';
import { EMERGENCY_PATH, stageName } from './labels';

// Quick views of the list (the engine's built-in views; "all" sends none).
const SUBJECT_MIN = 180; // the subject stays readable however narrow it is dragged
// Each column's own width, as the problems list (QA10V-06: the subject took ~750 px and squeezed
// the rest; at 390 px Updated was off-screen). The table scrolls sideways on a phone.
const OWN_WIDTHS = { id: 130, subject: 360, stage: 170, status: 170, updated: 170 };
const VIEWS = ['open', 'my_open', 'resolved', 'failed', 'all'] as const;
type View = (typeof VIEWS)[number];

/** Number or title: the list's search, as a filter the API applies to what you may see. */
function searchFilter(text: string): string | undefined {
  const needle = text.trim();
  if (needle === '') return undefined;
  return JSON.stringify({
    or: [
      { field: 'subject', op: 'contains', value: needle },
      { field: 'display_id', op: 'eq', value: needle.toUpperCase() },
    ],
  });
}

/**
 * The releases list on template C (D-147): the header with its count, one filter bar (quick
 * views and search), then the table, where the title takes the width left. Number, title, stage
 * and status, the emergency flag (REQ-REL-012 AC3), live on the type's list channel (a new
 * release appears at once, REQ-REL-007 AC3). On a phone the table scrolls in a region a keyboard
 * can reach.
 */
export function ReleasesPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { can } = useAccess();
  const { format } = useDateTime();
  const [view, setView] = useState<View>('open');
  // Each person's column widths, per view (Haider, 2026-11-10): drag or arrow keys on a header.
  const titles: Record<string, string> = {
    id: t('incidents.col.id'),
    subject: t('work_item.field.subject'),
    stage: t('work_item.field.stage'),
    status: t('work_item.field.status'),
    updated: t('releases.col.updated'),
  };
  const widths = useColumnWidths({
    kind: 'releases',
    viewKey: view,
    keys: Object.keys(titles),
    defaults: OWN_WIDTHS,
    minWidths: { subject: SUBJECT_MIN },
    label: (key) => t('layout.resize_column', { column: titles[key] ?? '' }),
  });
  const [search, setSearch] = useState('');
  const text = useDebounced(search, 300);
  const list = useReleases({
    view: view === 'all' ? undefined : view,
    filter: searchFilter(text),
    include_total: true,
  });
  usePageCrumbs([{ label: t('nav.releases') }]); // the tab's title too (QA6-REL-04)
  useListChannel('releases', () => {
    void queryClient.invalidateQueries({ queryKey: [...releaseKeys.all, 'list'] });
  });
  // Once per error, not on every render (lane A's review of #219).
  useEffect(() => {
    if (list.error) reportError(list.error);
  }, [list.error]);
  const settings = useReleaseSettings();
  const total = list.data?.estimated_total;
  return (
    <ListPage
      testId="releases-list"
      header={
        <PageHeader
          title={t('nav.releases')}
          count={total === undefined || total === null ? undefined : String(total)}
          testId="releases-header"
          extra={
            <Space>
              <Button
                onClick={() => void navigate('/releases/calendar')}
                data-testid="releases-calendar"
              >
                {t('releases.calendar.title')}
              </Button>
              {can('releases.create') && (
                <WriteButton
                  type="primary"
                  icon={<PlusOutlined />}
                  data-testid="new-release"
                  onClick={() => void navigate('/releases/new')}
                >
                  {t('releases.new')}
                </WriteButton>
              )}
            </Space>
          }
        />
      }
      filters={
        <FilterBar
          testId="releases-filters"
          view={
            // The view select as on every list (template C), not segmented tabs (QA10V-06).
            <Select<View>
              style={{ minWidth: 220 }}
              prefix={`${t('incidents.view')}:`}
              aria-label={t('incidents.view')}
              value={view}
              onChange={setView}
              options={VIEWS.map((code) => ({ value: code, label: t(`releases.view.${code}`) }))}
              data-testid="releases-view"
            />
          }
          search={
            <Input.Search
              allowClear
              aria-label={t('releases.search')}
              placeholder={t('releases.search')}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
              }}
              data-testid="releases-search"
            />
          }
          extra={
            widths.changed && (
              <Button onClick={widths.reset} data-testid="releases-reset-widths">
                {t('layout.reset_widths')}
              </Button>
            )
          }
        />
      }
    >
      <Table<ReleaseListItem>
        rowKey="id"
        data-testid="releases-table"
        loading={list.isPending}
        dataSource={list.data?.items ?? []}
        pagination={false}
        scroll={{ x: 960 }}
        components={widths.components}
        locale={{
          // Nothing to say while the first page loads: no "No releases yet." under the spinner
          // (QA10-P4-15).
          emptyText: loadedEmpty(
            list.isPending,
            t(text.trim() !== '' || view !== 'all' ? 'releases.no_match' : 'releases.empty'),
          ),
        }}
        onRow={(row) => ({
          onClick: () => void navigate(`/releases/${row.id}`),
          style: { cursor: 'pointer' },
          'data-testid': `release-row-${row.display_id}`,
        })}
        columns={[
          {
            key: 'id',
            title: t('incidents.col.id'),
            width: widths.width('id'),
            onHeaderCell: () => widths.header('id'),
            fixed: 'left' as const,
            // A link: the row's click alone left it unreachable by keyboard.
            render: (_, row) => (
              <Link
                to={`/releases/${row.id}`}
                style={{ color: 'inherit' }}
                onClick={(event) => {
                  event.stopPropagation(); // the row's own click would navigate again
                }}
                data-testid={`release-link-${row.display_id}`}
              >
                <strong dir="ltr" style={{ whiteSpace: 'nowrap' }}>
                  {row.display_id}
                </strong>
              </Link>
            ),
          },
          {
            key: 'subject',
            title: t('work_item.field.subject'),
            width: widths.width('subject'),
            onHeaderCell: () => widths.header('subject'),
            fixed: 'left' as const,
            render: (_, row) => (
              <Flex gap={8} align="center" style={{ minWidth: 0 }}>
                <CellText title={row.subject}>{row.subject}</CellText>
                {row.stage_path === EMERGENCY_PATH && (
                  <ToneTag
                    tone="error"
                    icon={<ThunderboltOutlined />}
                    testId={`release-emergency-${row.display_id}`}
                  >
                    {t('releases.emergency')}
                  </ToneTag>
                )}
              </Flex>
            ),
          },
          {
            key: 'stage',
            title: t('work_item.field.stage'),
            width: widths.width('stage'),
            onHeaderCell: () => widths.header('stage'),
            render: (_, row) => (
              <Tag data-testid={`release-stage-${row.display_id}`}>{stageName(t, row.stage)}</Tag>
            ),
          },
          {
            key: 'status',
            title: t('work_item.field.status'),
            width: widths.width('status'),
            onHeaderCell: () => widths.header('status'),
            // The dot chip of every list (QA10V-06), coloured by the type's own statuses.
            render: (_, row) => <StatusTag status={row.status} catalogue={settings.data} />,
          },
          {
            key: 'updated',
            title: t('releases.col.updated'),
            width: widths.width('updated'),
            onHeaderCell: () => widths.header('updated'),
            render: (_, row) => (
              <span style={{ whiteSpace: 'nowrap' }}>{format(row.updated_at)}</span>
            ),
          },
        ]}
      />
    </ListPage>
  );
}
