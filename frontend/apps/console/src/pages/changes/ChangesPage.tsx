import { PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Flex, Input, Select, Space, Table, Tag } from 'antd';
import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  changeKeys,
  useChanges,
  useStagedSettings,
  type ChangeListItem,
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
  useAppearance,
  useDateTime,
  useLabel,
  useColumnWidths,
} from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { BulkBar, BulkDialog, BulkProgress } from '../incidents/list/bulk';
import { useBulkRefresh, type Selection } from '../incidents/list/model';
import { StatusTag } from '../incidents/tags';
import { listValueName, stageName } from '../staged/labels';
import { ChangeBulkCancel } from './ChangeBulkCancel';
import { ChangeBulkClose } from './ChangeBulkClose';
import { EMERGENCY_PATH, riskTone } from './labels';

const CHANGE_BULK: readonly string[] = ['assign', 'take', 'close', 'cancel', 'delete'];
const SUBJECT_MIN = 180; // the subject stays readable however narrow it is dragged
const OWN_WIDTHS = {
  id: 130,
  subject: 340,
  path: 170,
  type: 150,
  risk: 120,
  stage: 170,
  status: 230, // "Awaiting acceptance" whole at 1470 px (QA F-11)
  updated: 170,
};
// The engine's built-in views a change list offers (labels `work_item_view.*`); "all" sends none.
// Pending approval: changes waiting at a stage's approval (acceptance, the plan, the CAB);
// then the CAB's own view, in implementation now, emergency and due for review (REQ-CHG-098).
const VIEWS = [
  'open',
  'my_open',
  'my_groups_open',
  'unassigned',
  'pending_approval',
  'awaiting_cab',
  'in_implementation',
  'emergency',
  'due_for_review',
  'overdue',
  'closed',
  'canceled',
  'all',
] as const;
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
 * The changes list on template C (D-147): the header with its count and New change, one filter
 * bar (the view and the search), then the table where the title takes the width left. Number,
 * title with the emergency flag, path, type, risk, stage and status, live on the type's list channel (a new
 * change or a move shows at once). On a phone the table scrolls in a region a keyboard reaches.
 */
export function ChangesPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { can } = useAccess();
  const { format } = useDateTime();
  const { locale } = useAppearance();
  const [view, setView] = useState<View>('open');
  const titles: Record<string, string> = {
    id: t('incidents.col.id'),
    subject: t('work_item.field.subject'),
    path: t('changes.col.path'),
    type: t('work_item.field.change_type'),
    risk: t('changes.col.risk'),
    stage: t('work_item.field.stage'),
    status: t('work_item.field.status'),
    updated: t('staged.col.updated'),
  };
  const widths = useColumnWidths({
    kind: 'changes',
    viewKey: view,
    keys: Object.keys(titles),
    defaults: OWN_WIDTHS,
    minWidths: { subject: SUBJECT_MIN },
    label: (key) => t('layout.resize_column', { column: titles[key] ?? '' }),
  });
  const [search, setSearch] = useState('');
  // Picked rows for bulk assign, take, close, cancel and trash (REQ-CHG-101; cancel and delete
  // since WP-046a S1's 0141). Edit and the CAB agenda come later, so they are not offered.
  const [selection, setSelection] = useState<Selection>({ ids: [], all: false });
  const [closing, setClosing] = useState(false);
  const [bulkAction, setBulkAction] = useState<'assign' | 'take' | null>(null);
  const [ending, setEnding] = useState<'cancel' | 'delete' | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const canBulk = can('changes.edit');
  const text = useDebounced(search, 300);
  const list = useChanges({
    view: view === 'all' ? undefined : view,
    filter: searchFilter(text),
    include_total: true,
  });
  usePageCrumbs([{ label: t('nav.changes') }]);
  useListChannel('changes', () => {
    void queryClient.invalidateQueries({ queryKey: changeKeys.list });
  });
  useBulkRefresh('change', () => {
    void queryClient.invalidateQueries({ queryKey: changeKeys.list });
  });
  useEffect(() => {
    if (list.error) reportError(list.error);
  }, [list.error]);
  const settings = useStagedSettings('changes');
  const total = list.data?.estimated_total;
  const rows = list.data?.items ?? [];
  const picked = rows.filter((row) => selection.ids.includes(row.id));
  const allFinal =
    !selection.all &&
    picked.length > 0 &&
    picked.every((row) => row.status_category === 'closed' || row.status_category === 'canceled');
  const selected = selection.ids.length > 0;
  // Type and risk come beside the rows (REQ-CHG-098); the risk is the one in force (chosen or scored).
  const facts = list.data?.changes ?? {};
  const typeName = (code: string | null | undefined) =>
    code
      ? listValueName(
          t,
          locale,
          'change_type',
          settings.data?.own_lists?.change_type?.find((v) => v.code === code),
          code,
        )
      : '';
  return (
    <ListPage
      testId="changes-list"
      header={
        <PageHeader
          title={t('nav.changes')}
          count={total === undefined || total === null ? undefined : String(total)}
          testId="changes-header"
          extra={
            <Space>
              <Button
                onClick={() => void navigate('/changes/calendar')}
                data-testid="changes-calendar"
              >
                {t('changes.calendar.title')}
              </Button>
              {can('changes.create') && (
                <WriteButton
                  type="primary"
                  icon={<PlusOutlined />}
                  data-testid="new-change"
                  onClick={() => void navigate('/changes/new')}
                >
                  {t('changes.new')}
                </WriteButton>
              )}
            </Space>
          }
        />
      }
      filters={
        // Rows picked: the selection bar takes the toolbar's place, as on incidents.
        selected ? (
          <BulkBar
            selection={selection}
            onSelection={setSelection}
            pageCount={rows.length}
            total={null}
            capped={false}
            onAction={(action) => {
              if (action === 'close') setClosing(true);
              else if (action === 'assign' || action === 'take') setBulkAction(action);
              else if (action === 'cancel' || action === 'delete') setEnding(action);
            }}
            // Changes already closed or cancelled can only go to the trash: take, assign,
            // close and cancel would only be skipped (QA 2026-11-12 F-08).
            canEdit={(action) => CHANGE_BULK.includes(action) && (action === 'delete' || !allFinal)}
            noun="changes"
          />
        ) : (
          <FilterBar
            testId="changes-filters"
            view={
              <Select<View>
                style={{ minWidth: 220 }}
                prefix={`${t('incidents.view')}:`}
                aria-label={t('incidents.view')}
                value={view}
                onChange={setView}
                options={VIEWS.map((code) => ({ value: code, label: t(`work_item_view.${code}`) }))}
                data-testid="changes-view"
              />
            }
            search={
              <Input.Search
                allowClear
                aria-label={t('staged.search')}
                placeholder={t('staged.search')}
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                }}
                data-testid="changes-search"
              />
            }
            extra={
              widths.changed && (
                <Button onClick={widths.reset} data-testid="changes-reset-widths">
                  {t('layout.reset_widths')}
                </Button>
              )
            }
          />
        )
      }
    >
      <ChangeBulkClose
        ids={selection.ids}
        open={closing}
        onClose={() => {
          setClosing(false);
        }}
        onStarted={(id) => {
          setClosing(false);
          setSelection({ ids: [], all: false });
          setJobId(id);
        }}
      />
      <ChangeBulkCancel
        ids={selection.ids}
        action={ending}
        onClose={() => {
          setEnding(null);
        }}
        onStarted={(id) => {
          setEnding(null);
          setSelection({ ids: [], all: false });
          setJobId(id);
        }}
      />
      <BulkDialog
        base="changes"
        action={bulkAction}
        count={selection.ids.length}
        request={{ recordIds: selection.ids }}
        onClose={() => {
          setBulkAction(null);
        }}
        onStarted={(job) => {
          setBulkAction(null);
          setSelection({ ids: [], all: false });
          setJobId(job.id);
        }}
      />
      <BulkProgress
        base="changes"
        jobId={jobId}
        onClose={() => {
          setJobId(null);
        }}
      />
      <Table<ChangeListItem>
        rowKey="id"
        data-testid="changes-table"
        loading={list.isPending}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 1350 }}
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
          emptyText: loadedEmpty(
            list.isPending,
            t(text.trim() !== '' || view !== 'all' ? 'changes.no_match' : 'changes.empty'),
          ),
        }}
        onRow={(row) => ({
          onClick: () => void navigate(`/changes/${row.id}`),
          style: { cursor: 'pointer' },
          'data-testid': `change-row-${row.display_id}`,
        })}
        columns={[
          {
            key: 'id',
            title: titles.id,
            width: widths.width('id'),
            onHeaderCell: () => widths.header('id'),
            fixed: 'left' as const,
            render: (_, row) => (
              <Link
                to={`/changes/${row.id}`}
                style={{ color: 'inherit' }}
                onClick={(event) => {
                  event.stopPropagation(); // the row's own click would navigate again
                }}
                data-testid={`change-link-${row.display_id}`}
              >
                <strong dir="ltr" style={{ whiteSpace: 'nowrap' }}>
                  {row.display_id}
                </strong>
              </Link>
            ),
          },
          {
            key: 'subject',
            title: titles.subject,
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
                    testId={`change-emergency-${row.display_id}`}
                  >
                    {t('changes.emergency')}
                  </ToneTag>
                )}
              </Flex>
            ),
          },
          {
            key: 'path',
            title: titles.path,
            width: widths.width('path'),
            onHeaderCell: () => widths.header('path'),
            render: (_, row) => (row.stage_path ? t(`stage_path.${row.stage_path}`) : ''),
          },
          {
            key: 'type',
            title: titles.type,
            width: widths.width('type'),
            onHeaderCell: () => widths.header('type'),
            render: (_, row) => (
              <CellText title={typeName(facts[row.id]?.change_type)}>
                {typeName(facts[row.id]?.change_type)}
              </CellText>
            ),
          },
          {
            key: 'risk',
            title: titles.risk,
            width: widths.width('risk'),
            onHeaderCell: () => widths.header('risk'),
            render: (_, row) => {
              const risk = facts[row.id]?.risk;
              return risk ? (
                <ToneTag tone={riskTone(risk)} testId={`change-risk-${row.display_id}`}>
                  {t(`risk_level.${risk}`)}
                </ToneTag>
              ) : null;
            },
          },
          {
            key: 'stage',
            title: titles.stage,
            width: widths.width('stage'),
            onHeaderCell: () => widths.header('stage'),
            render: (_, row) => (
              <Tag data-testid={`change-stage-${row.display_id}`}>{stageName(t, row.stage)}</Tag>
            ),
          },
          {
            key: 'status',
            title: titles.status,
            width: widths.width('status'),
            onHeaderCell: () => widths.header('status'),
            render: (_, row) => <StatusTag status={row.status} catalogue={settings.data} />,
          },
          {
            key: 'updated',
            title: titles.updated,
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
