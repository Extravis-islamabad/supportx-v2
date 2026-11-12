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
  useAppearance,
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
import { ChangeBulkCancel } from '../changes/ChangeBulkCancel';
import { ChangeBulkClose } from '../changes/ChangeBulkClose';
import { BulkBar, BulkDialog, BulkProgress } from '../incidents/list/bulk';
import type { Selection } from '../incidents/list/model';
import { StatusTag } from '../incidents/tags';
import { EMERGENCY_PATH, listValueName, stageName } from './labels';
import { useOwnList } from './lists';
import { ReleaseBulkRole } from './ReleaseBulkRole';

// Quick views of the list (the engine's built-in views; "all" sends none).
const SUBJECT_MIN = 180; // the subject stays readable however narrow it is dragged
// Each column's own width, as the problems list (QA10V-06: the subject took ~750 px and squeezed
// the rest; at 390 px Updated was off-screen). The table scrolls sideways on a phone.
const OWN_WIDTHS = {
  id: 130,
  subject: 320,
  type: 150,
  stage: 170,
  status: 200,
  priority: 110,
  manager: 170,
  engineer: 170,
  version: 120,
  end: 170,
  tasks: 110,
  updated: 170,
};
// The release list's views (REQ-REL-055, Appendix A; labels `work_item_view.*`).
const VIEWS = [
  'open',
  'my_releases',
  'release_unassigned',
  'scheduled',
  'unscheduled',
  'deployed',
  'failed',
  'canceled',
  'closed',
  'all',
] as const;
// What the list does to picked releases (REQ-REL-057), each release by its own rules.
const RELEASE_BULK: readonly string[] = [
  'assign',
  'assign_role',
  'take',
  'close',
  'cancel',
  'delete',
];
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
  const { locale } = useAppearance();
  const [view, setView] = useState<View>('open');
  // Each person's column widths, per view (Haider, 2026-11-10): drag or arrow keys on a header.
  const titles: Record<string, string> = {
    id: t('incidents.col.id'),
    subject: t('work_item.field.subject'),
    type: t('work_item.field.release_type'),
    stage: t('work_item.field.stage'),
    status: t('work_item.field.status'),
    priority: t('work_item.field.priority'),
    manager: t('work_item_role.release_manager'),
    engineer: t('work_item_role.release_engineer'),
    version: t('work_item.field.release_version'),
    end: t('work_item.field.scheduled_end'),
    tasks: t('releases.col.tasks'),
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
  // Picked rows for the bulk actions (REQ-REL-057).
  const [selection, setSelection] = useState<Selection>({ ids: [], all: false });
  const [closing, setClosing] = useState(false);
  const [roling, setRoling] = useState(false);
  const [bulkAction, setBulkAction] = useState<'assign' | 'take' | null>(null);
  const [ending, setEnding] = useState<'cancel' | 'delete' | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const canBulk = can('releases.edit');
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
  const types = useOwnList('release_type');
  const total = list.data?.estimated_total;
  const rows = list.data?.items ?? [];
  const selected = selection.ids.length > 0;
  // Each row's own columns and the people on them come beside the rows (REQ-REL-055).
  const facts = list.data?.releases ?? {};
  const people = list.data?.people ?? {};
  const personName = (id: string | null | undefined) =>
    id ? (people[id]?.display_name ?? '') : '';
  const typeName = (code: string | null | undefined) =>
    listValueName(
      t,
      locale,
      'release_type',
      types.find((v) => v.code === code),
      code,
    );
  const startedJob = (id: string) => {
    setSelection({ ids: [], all: false });
    setJobId(id);
  };
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
        selected ? (
          <BulkBar
            selection={selection}
            onSelection={setSelection}
            pageCount={rows.length}
            total={null}
            capped={false}
            onAction={(action) => {
              if (action === 'close') setClosing(true);
              else if (action === 'assign_role') setRoling(true);
              else if (action === 'assign' || action === 'take') setBulkAction(action);
              else if (action === 'cancel' || action === 'delete') setEnding(action);
            }}
            canEdit={(action) => RELEASE_BULK.includes(action)}
            noun="releases"
          />
        ) : (
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
        )
      }
    >
      <ChangeBulkClose
        base="releases"
        ids={selection.ids}
        open={closing}
        onClose={() => {
          setClosing(false);
        }}
        onStarted={(id) => {
          setClosing(false);
          startedJob(id);
        }}
      />
      <ChangeBulkCancel
        base="releases"
        ids={selection.ids}
        action={ending}
        onClose={() => {
          setEnding(null);
        }}
        onStarted={(id) => {
          setEnding(null);
          startedJob(id);
        }}
      />
      <ReleaseBulkRole
        ids={selection.ids}
        open={roling}
        onClose={() => {
          setRoling(false);
        }}
        onStarted={(id) => {
          setRoling(false);
          startedJob(id);
        }}
      />
      <BulkDialog
        base="releases"
        action={bulkAction}
        count={selection.ids.length}
        request={{ recordIds: selection.ids }}
        onClose={() => {
          setBulkAction(null);
        }}
        onStarted={(job) => {
          setBulkAction(null);
          startedJob(job.id);
        }}
      />
      <BulkProgress
        base="releases"
        jobId={jobId}
        onClose={() => {
          setJobId(null);
        }}
      />
      <Table<ReleaseListItem>
        rowKey="id"
        data-testid="releases-table"
        loading={list.isPending}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 2050 }}
        components={widths.components}
        rowSelection={
          canBulk
            ? {
                fixed: true,
                selectedRowKeys: selection.ids,
                onChange: (keys) => {
                  setSelection({ ids: keys.map(String), all: false });
                },
                getCheckboxProps: (row) => ({
                  title: t('incidents.bulk.select_row', { id: row.display_id }),
                }),
              }
            : undefined
        }
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
            key: 'type',
            title: titles.type,
            width: widths.width('type'),
            onHeaderCell: () => widths.header('type'),
            render: (_, row) => (
              <CellText title={typeName(facts[row.id]?.release_type)}>
                {typeName(facts[row.id]?.release_type)}
              </CellText>
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
            key: 'priority',
            title: titles.priority,
            width: widths.width('priority'),
            onHeaderCell: () => widths.header('priority'),
            render: (_, row) => t(`priority.${row.priority}`),
          },
          ...(['manager', 'engineer'] as const).map((key) => ({
            key,
            title: titles[key],
            width: widths.width(key),
            onHeaderCell: () => widths.header(key),
            render: (_: unknown, row: ReleaseListItem) => {
              const fact = facts[row.id];
              const name = personName(
                key === 'manager' ? fact?.release_manager_id : fact?.release_engineer_id,
              );
              return <CellText title={name}>{name}</CellText>;
            },
          })),
          {
            key: 'version',
            title: titles.version,
            width: widths.width('version'),
            onHeaderCell: () => widths.header('version'),
            render: (_, row) => <bdi dir="ltr">{facts[row.id]?.release_version ?? ''}</bdi>,
          },
          {
            key: 'end',
            title: titles.end,
            width: widths.width('end'),
            onHeaderCell: () => widths.header('end'),
            render: (_, row) => {
              const end = facts[row.id]?.scheduled_end;
              return end ? <span style={{ whiteSpace: 'nowrap' }}>{format(end)}</span> : '';
            },
          },
          {
            key: 'tasks',
            title: titles.tasks,
            width: widths.width('tasks'),
            onHeaderCell: () => widths.header('tasks'),
            render: (_, row) => {
              const fact = facts[row.id];
              return fact && fact.tasks_total > 0
                ? t('releases.tasks_done', { done: fact.tasks_done, total: fact.tasks_total })
                : '';
            },
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
