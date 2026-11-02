import { useQueryClient } from '@tanstack/react-query';
import { Alert, App, Button, Flex, Segmented, Select, Space, Table, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';

import { useListFormat } from '@supportx/labels';

import {
  allOf,
  queryKeys,
  useCustomFields,
  useIncidentCatalogue,
  useIncidents,
  useIncidentCounters,
  useIncidentListFields,
  useIncidentViewFilters,
  useIncidentViews,
  useListSetting,
  useRestoreIncident,
  useSavedViews,
  useSaveListSetting,
  useUnits,
  type BulkAction,
  type BulkJob,
  type FilterExpression,
  type IncidentListItem,
  type ListColumn,
  type SavedView,
} from '@supportx/api-client';
import {
  refreshList,
  refreshRecord,
  useListChannel,
  usePersonalChannel,
  useTenantChannel,
} from '@supportx/realtime';
import {
  ConflictDialog,
  useConflictRetry,
  EmptyText,
  NoAccess,
  reportError,
  useAccess,
  useAppearance,
  useDateTime,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { choiceName, fieldName } from '../customFields/values';
import { useReportWords } from '../reports/names';
import { useIncidentFieldName } from './conflict';
import { scaleLabel } from './labels';
import { COUNTERS } from './counters';
import { PersonalCounters } from './PersonalCounters';
import { BulkBar, BulkDialog, BulkJobsButton, BulkProgress } from './list/bulk';
import { ColumnChooser, ResizableHeader, SelectPageBox } from './list/ColumnChooser';
import { chosenColumns, columnCatalogue, sortOf, type ColumnContext } from './list/columns';
import { ListExport } from './list/ListExport';
import {
  chipsFilter,
  draftOf,
  exportFilter,
  rangeFilter,
  useBulkLive,
  type SearchChip,
  type Selection,
  type TimeRangeValue,
  type ViewDraft,
} from './list/model';
import { SearchChips } from './list/SearchChips';
import { TimeRange } from './list/TimeRange';
import { ViewEditor } from './list/ViewEditor';
import { SEARCH_DELAY_MS, useDebounced } from '../../useDebounced';

const SORTS = ['-updated_at', '-created_at', 'priority', 'display_number', 'subject'] as const;
const PRIORITIES = ['p1', 'p2', 'p3', 'p4'] as const;
const DEFAULT_VIEW = 'open';
const PAGE_SIZES = [25, 50, 100] as const;
const CUSTOM = 'custom:';
const LISTS_CHANGED = 'work_items.lists_changed';
const VIEWS_CHANGED = 'work_items.views_changed';
const SETTINGS_CHANGED = 'work_items.list_settings_changed';
// On my own channel, what changes only my counts (WP-020d QA BUG-01): a follow or a reply by
// someone else, a direct report gained or lost, a group joined or left. Someone who sees every
// incident follows only the shared list channel, which never hears about these.
const MY_COUNTS_CHANGED = new Set([LISTS_CHANGED, 'users.reports_changed', 'access.changed']);
const ID_PATTERN = /^([A-Za-z]{2,6}-)?\d{1,18}$/;

/** Subject words, or a display ID ("INC-12", "12"), in one search box. */
function searchOf(text: string): FilterExpression | undefined {
  if (text === '') return undefined;
  const subject: FilterExpression = { field: 'subject', op: 'contains', value: text };
  if (!ID_PATTERN.test(text)) return subject;
  const number = Number(text.replace(/^[A-Za-z]+-/, ''));
  return { or: [subject, { field: 'display_number', op: 'eq', value: number }] };
}

/**
 * Incidents (REQ-INC-104 to 110, 119, 120): built-in and saved views with live counts, chosen
 * columns per view, a time range, search with chips, a page size, sorting across pages, selection
 * across pages with bulk changes, and the export; live (REQ-WI-005). A view never hides records
 * silently (REQ-INC-152): the page says which view is active and how many records it leaves out.
 */
export function IncidentsPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const dates = useDateTime();
  const { can } = useAccess();
  const allowed = can('incidents.view');
  const [mode, setMode] = useState<'current' | 'trash'>('current');
  // A built-in view code, or `custom:<saved view id>`.
  const [view, setView] = useState<string>(DEFAULT_VIEW);
  // A filter tried without saving (REQ-INC-106 AC2): this screen only.
  const [trying, setTrying] = useState<FilterExpression | undefined>();
  const [editing, setEditing] = useState<ViewDraft | null>(null);
  const [search, setSearch] = useState('');
  const [chips, setChips] = useState<SearchChip[]>([]);
  const [range, setRange] = useState<TimeRangeValue>();
  const [priority, setPriority] = useState<string>();
  // One custom field filter (WP-026, REQ-INC-014 AC1): a pick list or yes/no field and a value.
  const [customKey, setCustomKey] = useState<string>();
  const [customValue, setCustomValue] = useState<string>();
  // The selection belongs to one list: a new view, filter or trash starts empty ("all N" meant
  // the old list).
  const [picked, setPicked] = useState<Selection & { list: string }>({
    ids: [],
    all: false,
    list: '',
  });
  const [bulkAction, setBulkAction] = useState<BulkAction | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const text = useDebounced(search.trim(), SEARCH_DELAY_MS);
  const trash = mode === 'trash';
  const customFields = useCustomFields('incident', false, allowed);
  const savedViews = useSavedViews(allowed && !trash);
  const saved: SavedView | undefined = view.startsWith(CUSTOM)
    ? savedViews.data?.find((v) => v.id === view.slice(CUSTOM.length))
    : undefined;
  const builtIn = view.startsWith(CUSTOM) ? null : view;
  const settingKey = trash ? 'all' : view;
  const setting = useListSetting(settingKey, allowed);
  const saveSetting = useSaveListSetting();
  const listFields = useIncidentListFields(allowed);
  const viewFilters = useIncidentViewFilters(allowed && !trash);
  const words = useReportWords();
  const { locale } = useAppearance();
  const listFormat = useListFormat();
  const zone = dates.zone;
  const filterable = (customFields.data ?? []).filter(
    (f) =>
      f.field_type === 'choice' || f.field_type === 'multi_choice' || f.field_type === 'yes_no',
  );
  const customField = filterable.find((f) => f.key === customKey);
  const customCondition: FilterExpression | undefined =
    customField === undefined || customValue === undefined
      ? undefined
      : {
          field: `custom.${customField.key}`,
          op: 'eq',
          value: customField.field_type === 'yes_no' ? customValue === 'yes' : customValue,
        };
  // What narrows the view on this screen (search, chips, time range, quick filters).
  const narrowing = useMemo(
    () =>
      allOf(
        searchOf(text),
        chipsFilter(chips),
        rangeFilter(range, zone),
        priority === undefined ? undefined : { field: 'priority', op: 'eq', value: priority },
        customCondition,
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the condition is derived from these
    [text, chips, range, zone, priority, customField?.key, customField?.field_type, customValue],
  );
  const viewFilter = trying ?? (saved?.filter as FilterExpression | null | undefined) ?? undefined;
  const filter = useMemo(() => allOf(viewFilter, narrowing), [viewFilter, narrowing]);

  // Columns, sort and page size: yours for this view, else the saved view's, else the defaults.
  const catalogue = useIncidentCatalogue(allowed);
  const fields = useMemo(() => listFields.data ?? [], [listFields.data]);
  const columnSpecs = useMemo(() => columnCatalogue(fields), [fields]);
  const stored = setting.data;
  const columns = chosenColumns(
    stored?.version != null ? stored.columns : (saved?.columns ?? []),
    columnSpecs,
  );
  const sort = stored?.sort ?? saved?.sort ?? '-updated_at';
  const pageSize = stored?.page_size ?? 50;
  const saveSettings = (change: { columns?: ListColumn[]; sort?: string; page_size?: number }) => {
    saveSetting.mutate(
      {
        viewKey: settingKey,
        version: stored?.version ?? null,
        setting: {
          columns: change.columns ?? columns,
          sort: change.sort ?? sort,
          page_size: change.page_size ?? pageSize,
        },
      },
      { onError: reportError },
    );
  };

  const list = useIncidents(
    { view: builtIn ?? undefined, filter, sort, limit: pageSize, trash },
    allowed && (builtIn !== null || saved !== undefined || trash),
  );
  const views = useIncidentViews(allowed && !trash);
  // Counter views say what they leave out like the built-in ones (Area 15; QA BUG-06).
  const counters = useIncidentCounters(allowed && !trash);
  const groups = useUnits('groups', allowed);
  const groupNames = new Map((groups.data ?? []).map((g) => [g.id, g.name]));

  const queryClient = useQueryClient();
  const refreshLists = () => {
    refreshList(queryClient, [...queryKeys.incidents.all, 'list']);
    refreshList(queryClient, queryKeys.incidents.views);
    refreshList(queryClient, queryKeys.incidents.counters);
  };
  useListChannel(allowed ? 'incidents' : null, (message) => {
    refreshLists();
    for (const id of message.ids) {
      refreshRecord(queryClient, queryKeys.incidents.detail(id), message);
    }
  });
  useTenantChannel((message) => {
    // A bulk job's batch: one refresh for the whole batch (REQ-INC-120), not one per record.
    if (message.type === LISTS_CHANGED) refreshLists();
    if (message.type === VIEWS_CHANGED) refreshList(queryClient, queryKeys.incidents.savedViews);
  });
  usePersonalChannel((message) => {
    if (MY_COUNTS_CHANGED.has(message.type)) refreshLists();
    if (message.type === VIEWS_CHANGED) refreshList(queryClient, queryKeys.incidents.savedViews);
    if (message.type === SETTINGS_CHANGED && message.ids.includes(settingKey)) {
      refreshList(queryClient, queryKeys.incidents.listSetting(settingKey));
    }
  });
  useBulkLive();
  const listKey = JSON.stringify([view, filter ?? null, trash]);
  const selection: Selection = picked.list === listKey ? picked : { ids: [], all: false };
  const setSelection = (next: Selection) => {
    setPicked({ ...next, list: listKey });
  };

  const rows = useMemo(() => list.data?.pages.flatMap((page) => page.items) ?? [], [list.data]);
  const people = useMemo(
    () =>
      Object.assign({}, ...(list.data?.pages.map((p) => p.people) ?? [])) as Record<
        string,
        { display_name: string; email: string }
      >,
    [list.data],
  );
  if (!allowed) return <NoAccess titleKey="nav.incidents" />;
  const counts = new Map(
    [...(views.data ?? []), ...(counters.data ?? []).map((c) => ({ ...c, view: c.counter }))].map(
      (v) => [v.view, { count: v.count, capped: v.capped }],
    ),
  );
  const total = list.data?.pages[0]?.estimated_total ?? null;
  const context: ColumnContext = {
    t,
    words,
    dates,
    catalogue: catalogue.data,
    people,
    groupNames,
    locale,
    list: listFormat,
  };
  const current = sortOf(sort);
  const mine = (savedViews.data ?? []).filter((v) => v.mine);
  const shared = (savedViews.data ?? []).filter((v) => !v.mine);
  const viewName = saved?.name ?? t(`work_item_view.${view}`);
  const exported = exportFilter(builtIn, viewFilters.data, filter);
  const bulkAllowed = (action: BulkAction) =>
    can(action === 'resolve' || action === 'close' ? 'incidents.edit' : `incidents.${action}`);

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Flex justify="space-between" align="center" wrap gap={12}>
        <Typography.Title level={1} style={{ margin: 0 }}>
          {t('incidents.title')}
        </Typography.Title>
        <Space wrap>
          {!trash && (
            <ListExport
              title={viewName}
              filter={exported}
              columns={columns.map((c) => c.key)}
              sort={sort}
            />
          )}
          {!trash && <BulkJobsButton onOpen={setJobId} />}
          {can('incidents.delete') && (
            <Segmented<'current' | 'trash'>
              value={mode}
              onChange={setMode}
              options={[
                { value: 'current', label: t('incidents.current') },
                { value: 'trash', label: t('incidents.trash') },
              ]}
              data-testid="inc-mode"
            />
          )}
          {can('incidents.create') && (
            <WriteButton
              type="primary"
              onClick={() => void navigate('/incidents/new')}
              data-testid="inc-new"
            >
              {t('incidents.new')}
            </WriteButton>
          )}
        </Space>
      </Flex>
      {!trash && (
        <PersonalCounters
          active={view}
          onOpen={(code) => {
            setTrying(undefined);
            setView(code);
          }}
        />
      )}
      {/* Two rows, each narrower than a desktop screen (WP-020d QA BUG-02): what to look at
          (view and search, whose chips add height only), then how to narrow and show it. One
          row of everything was wider than the screen, so items wrapped wherever they fell. */}
      <Flex gap={12} wrap align="start" data-testid="inc-toolbar-find">
        {!trash && (
          // Straight in the row, not a wrapping box of their own: Chrome sizes such a box to its
          // widest child, which pushed "New view" under the selector (BUG-02). The row still
          // wraps them on a phone.
          <>
            <Select
              aria-label={t('incidents.view')}
              // Many views: searchable by name.
              showSearch
              optionFilterProp="label"
              prefix={`${t('incidents.view')}:`}
              value={view}
              onChange={(next: string) => {
                setTrying(undefined);
                setView(next);
              }}
              options={[
                {
                  label: t('incidents.views.built_in'),
                  title: t('incidents.views.built_in'),
                  options: [
                    ...(views.data ?? [{ view: DEFAULT_VIEW, count: 0, capped: false }]).map(
                      (v) => ({
                        value: v.view,
                        label: `${t(`work_item_view.${v.view}`)} (${String(v.count)}${v.capped ? '+' : ''})`,
                      }),
                    ),
                    // A personal counter opened its view (REQ-INC-128 AC2): name it like the others.
                    ...((COUNTERS as readonly string[]).includes(view)
                      ? [{ value: view, label: t(`work_item_view.${view}`) }]
                      : []),
                  ],
                },
                ...(mine.length > 0
                  ? [
                      {
                        label: t('incidents.views.mine'),
                        title: t('incidents.views.mine'),
                        options: mine.map((v) => ({ value: `${CUSTOM}${v.id}`, label: v.name })),
                      },
                    ]
                  : []),
                ...(shared.length > 0
                  ? [
                      {
                        label: t('incidents.views.shared_with_me'),
                        title: t('incidents.views.shared_with_me'),
                        options: shared.map((v) => ({ value: `${CUSTOM}${v.id}`, label: v.name })),
                      },
                    ]
                  : []),
              ]}
              style={{ width: 'min(260px, 100%)' }}
              data-testid="inc-view"
            />
            {saved?.mine === true && (
              <Button
                onClick={() => {
                  setEditing(draftOf(saved));
                }}
                data-testid="inc-view-edit"
              >
                {t('incidents.views.edit')}
              </Button>
            )}
            <Button
              onClick={() => {
                setEditing(draftOf(undefined));
              }}
              data-testid="inc-view-new"
            >
              {t('incidents.views.new')}
            </Button>
          </>
        )}
        <SearchChips
          text={search}
          onText={setSearch}
          chips={chips}
          onChips={setChips}
          fields={fields}
          words={words}
        />
      </Flex>
      <Flex gap={12} wrap align="center" data-testid="inc-toolbar-narrow">
        <Select
          aria-label={t('work_item.field.priority')}
          prefix={`${t('work_item.field.priority')}:`}
          value={priority ?? ''}
          onChange={(value) => {
            setPriority(value === '' ? undefined : value);
          }}
          options={[
            { value: '', label: t('users.any') },
            ...PRIORITIES.map((p) => ({
              value: p,
              label: scaleLabel(t, catalogue.data, 'priority', p, locale),
            })),
          ]}
          style={{ minWidth: 'min(200px, 100%)' }}
          data-testid="inc-filter-priority"
        />
        {filterable.length > 0 && (
          <Space.Compact>
            <Select
              aria-label={t('custom_fields.filter_field')}
              placeholder={t('custom_fields.filter_field')}
              allowClear
              value={customField?.key}
              onChange={(key: string | undefined) => {
                setCustomKey(key);
                setCustomValue(undefined);
              }}
              // Retired fields still find old records, under their own heading (D-091, O5).
              options={[
                ...filterable
                  .filter((f) => !f.retired)
                  .map((f) => ({ value: f.key, label: fieldName(f, locale) })),
                ...(filterable.some((f) => f.retired)
                  ? [
                      {
                        label: t('custom_fields.retired_fields'),
                        title: t('custom_fields.retired_fields'),
                        options: filterable
                          .filter((f) => f.retired)
                          .map((f) => ({ value: f.key, label: fieldName(f, locale) })),
                      },
                    ]
                  : []),
              ]}
              style={{ minWidth: 'min(180px, 100%)' }}
              data-testid="inc-filter-custom-field"
            />
            {customField !== undefined && (
              <Select
                aria-label={t('custom_fields.filter_value', {
                  field: fieldName(customField, locale),
                })}
                placeholder={t('users.any')}
                allowClear
                value={customValue}
                onChange={(value: string | undefined) => {
                  setCustomValue(value);
                }}
                options={
                  customField.field_type === 'yes_no'
                    ? [
                        { value: 'yes', label: t('custom_fields.yes') },
                        { value: 'no', label: t('custom_fields.no') },
                      ]
                    : customField.choices.map((c) => ({
                        value: c.code ?? '',
                        label: choiceName(t, customField, c.code ?? '', locale),
                      }))
                }
                style={{ minWidth: 'min(180px, 100%)' }}
                data-testid="inc-filter-custom-value"
              />
            )}
          </Space.Compact>
        )}
        <Select
          aria-label={t('users.sort')}
          prefix={`${t('users.sort')}:`}
          value={sort}
          onChange={(next: string) => {
            saveSettings({ sort: next });
          }}
          options={[
            ...SORTS.map((s) => ({ value: s, label: t(`incidents.sort.${s}`) })),
            // A column's sort (any sortable field) names its column and direction.
            ...((SORTS as readonly string[]).includes(sort)
              ? []
              : [
                  {
                    value: sort,
                    label: t(current.descending ? 'incidents.sort.desc' : 'incidents.sort.asc', {
                      field: words.field(current.field),
                    }),
                  },
                ]),
          ]}
          style={{ minWidth: 'min(220px, 100%)' }}
          data-testid="inc-sort"
        />
        <Select<number>
          aria-label={t('incidents.page_size')}
          prefix={`${t('incidents.page_size')}:`}
          value={pageSize}
          onChange={(next) => {
            saveSettings({ page_size: next });
          }}
          options={PAGE_SIZES.map((n) => ({ value: n, label: String(n) }))}
          data-testid="inc-page-size"
        />
        <ColumnChooser
          columns={columns}
          catalogue={columnSpecs}
          context={context}
          onChange={(next) => {
            saveSettings({ columns: next });
          }}
        />
      </Flex>
      <TimeRange value={range} onChange={setRange} words={words} />
      {trying !== undefined && (
        <Alert
          type="warning"
          showIcon
          data-testid="inc-trying"
          message={t('incidents.views.trying')}
          action={
            <Button
              size="small"
              onClick={() => {
                setTrying(undefined);
              }}
            >
              {t('incidents.views.stop_trying')}
            </Button>
          }
        />
      )}
      {!trash && (
        <ViewNotice
          view={view}
          name={viewName}
          inView={builtIn !== null ? counts.get(view)?.count : (total ?? undefined)}
          everything={counts.get('all')}
          filtered={narrowing !== undefined}
          shown={total}
          onShowAll={() => {
            setTrying(undefined);
            setView('all');
          }}
        />
      )}
      {!trash && (
        <BulkBar
          selection={selection}
          onSelection={setSelection}
          pageCount={rows.length}
          total={total}
          capped={total !== null && total >= 1000 && list.hasNextPage}
          onAction={setBulkAction}
          canEdit={bulkAllowed}
        />
      )}
      <Table<IncidentListItem>
        rowKey="id"
        data-testid="inc-table"
        loading={list.isPending && list.fetchStatus === 'fetching'}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 'max-content' }}
        components={{ header: { cell: ResizableHeader } }}
        rowSelection={
          trash
            ? undefined
            : {
                selectedRowKeys: selection.all ? rows.map((r) => r.id) : selection.ids,
                columnTitle: (
                  <SelectPageBox
                    checked={
                      rows.length > 0 && (selection.all || selection.ids.length === rows.length)
                    }
                    indeterminate={
                      !selection.all &&
                      selection.ids.length > 0 &&
                      selection.ids.length < rows.length
                    }
                    onChange={(checked) => {
                      setSelection({ ids: checked ? rows.map((r) => r.id) : [], all: false });
                    }}
                    label={t('incidents.bulk.select_page')}
                  />
                ),
                onChange: (keys) => {
                  setSelection({ ids: keys.map(String), all: false });
                },
                getCheckboxProps: (row) => ({
                  title: t('incidents.bulk.select_row', { id: row.display_id }),
                }),
              }
        }
        locale={{
          emptyText: (
            <EmptyText>{t(trash ? 'incidents.trash_empty' : 'incidents.empty')}</EmptyText>
          ),
        }}
        onChange={(_pagination, _filters, sorter) => {
          const one = Array.isArray(sorter) ? sorter[0] : sorter;
          const spec = columnSpecs.get(String(one?.columnKey ?? ''));
          if (spec?.sortField === undefined) return;
          const next =
            one?.order === 'ascend'
              ? spec.sortField
              : one?.order === 'descend'
                ? `-${spec.sortField}`
                : '-updated_at';
          saveSettings({ sort: next });
        }}
        onRow={(row) =>
          trash
            ? { 'data-testid': `inc-row-${row.display_id}` }
            : {
                onClick: () => void navigate(`/incidents/${row.id}`),
                style: { cursor: 'pointer' },
                'data-testid': `inc-row-${row.display_id}`,
              }
        }
        columns={[
          ...columns.flatMap((column) => {
            const spec = columnSpecs.get(column.key);
            if (spec === undefined) return [];
            const width = column.width ?? spec.width;
            return [
              {
                key: spec.key,
                title: spec.title(context),
                width,
                ellipsis: spec.key === 'subject',
                // Server-side sort, across every page (REQ-INC-104 AC2).
                sorter: spec.sortField !== undefined,
                sortOrder:
                  spec.sortField !== undefined && current.field === spec.sortField
                    ? current.descending
                      ? ('descend' as const)
                      : ('ascend' as const)
                    : null,
                render: (_: unknown, row: IncidentListItem) => spec.render(row, context),
                onHeaderCell: () =>
                  ({
                    width,
                    resizeLabel: t('incidents.columns.resize', { column: spec.title(context) }),
                    onResize: (next: number) => {
                      saveSettings({
                        columns: columns.map((c) =>
                          c.key === column.key ? { ...c, width: next } : c,
                        ),
                      });
                    },
                  }) as React.HTMLAttributes<HTMLElement>,
              },
            ];
          }),
          ...(trash
            ? [
                {
                  key: 'restore',
                  title: t('incidents.restore'),
                  fixed: 'right' as const, // always in view, however wide the table (QA BUG-16)
                  width: 130,
                  render: (_: unknown, row: IncidentListItem) => <RestoreButton row={row} />,
                },
              ]
            : []),
        ]}
      />
      {list.hasNextPage && (
        <Flex justify="center">
          <Button
            onClick={() => void list.fetchNextPage()}
            loading={list.isFetchingNextPage}
            data-testid="inc-more"
          >
            {t('incidents.more')}
          </Button>
        </Flex>
      )}
      <ViewEditor
        draft={editing}
        onClose={() => {
          setEditing(null);
        }}
        onApply={(tried) => {
          setTrying(tried);
          setEditing(null);
        }}
        onSaved={(view: SavedView | null) => {
          setEditing(null);
          setTrying(undefined);
          setView(view === null ? DEFAULT_VIEW : `${CUSTOM}${view.id}`);
        }}
        fields={fields}
        words={words}
        columns={columns}
        sort={sort}
      />
      <BulkDialog
        action={bulkAction}
        count={selection.all ? (total ?? 0) : selection.ids.length}
        request={
          selection.all
            ? { query: { view: builtIn ?? undefined, filter } }
            : { recordIds: selection.ids }
        }
        onClose={() => {
          setBulkAction(null);
        }}
        onStarted={(job: BulkJob) => {
          setBulkAction(null);
          setSelection({ ids: [], all: false });
          setJobId(job.id);
        }}
      />
      <BulkProgress
        jobId={jobId}
        onClose={() => {
          setJobId(null);
        }}
      />
    </Space>
  );
}

/**
 * Which view is active and what it leaves out (Area 15: no silent hiding). "Everything" counts
 * all incidents the user may see; the difference is what the view (plus search) does not show.
 */
function ViewNotice({
  view,
  name,
  inView,
  everything,
  filtered,
  shown,
  onShowAll,
}: {
  view: string;
  name: string;
  inView: number | undefined;
  everything: { count: number; capped: boolean } | undefined;
  filtered: boolean;
  shown: number | null;
  onShowAll: () => void;
}) {
  const t = useLabel();
  if (inView === undefined || everything === undefined) return null;
  const hidden = Math.max(0, everything.count - inView);
  const parts = [t('incidents.view_notice', { view: name, count: inView })];
  if (filtered && shown !== null) parts.push(t('incidents.filter_notice', { count: shown }));
  if (view !== 'all' && hidden > 0) {
    parts.push(
      t(everything.capped ? 'incidents.hidden_notice_capped' : 'incidents.hidden_notice', {
        count: hidden,
      }),
    );
  }
  return (
    <Alert
      type="info"
      showIcon
      role="status"
      data-testid="inc-view-notice"
      data-hidden={hidden}
      message={parts.join(' ')}
      action={
        view !== 'all' && hidden > 0 ? (
          <Button size="small" onClick={onShowAll} data-testid="inc-show-all">
            {t('incidents.show_all')}
          </Button>
        ) : undefined
      }
    />
  );
}

function RestoreButton({ row }: { row: IncidentListItem }) {
  const t = useLabel();
  const { message } = App.useApp();
  const restore = useRestoreIncident();
  // Changed by someone after the list showed it (409): the shared dialog (QA WP-029 BUG-05).
  const conflict = useConflictRetry();
  const fieldName = useIncidentFieldName();
  const run = (version: number) => {
    restore.mutate(
      { id: row.id, version },
      {
        onSuccess: () => void message.success(t('incidents.restored')),
        onError: (error) => {
          if (!conflict.take(error, run)) reportError(error);
        },
      },
    );
  };
  return (
    <>
      <WriteButton
        size="small"
        loading={restore.isPending}
        data-testid={`inc-restore-${row.display_id}`}
        onClick={() => {
          run(row.version);
        }}
      >
        {t('incidents.restore')}
      </WriteButton>
      <ConflictDialog {...conflict.dialog} fieldLabel={fieldName} />
    </>
  );
}
