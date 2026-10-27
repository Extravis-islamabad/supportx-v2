import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Flex,
  Input,
  Segmented,
  Select,
  Space,
  Table,
  Tooltip,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';

import {
  allOf,
  queryKeys,
  useCustomFields,
  useIncidentCatalogue,
  useIncidents,
  useIncidentCounters,
  useIncidentViews,
  useRestoreIncident,
  useUnits,
  type FilterExpression,
  type IncidentListItem,
} from '@supportx/api-client';
import { refreshList, refreshRecord, useListChannel } from '@supportx/realtime';
import {
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
import { personName, scaleLabel } from './labels';
import { COUNTERS } from './counters';
import { PersonalCounters } from './PersonalCounters';
import { PriorityTag, SlaTag, StatusTag } from './tags';
import { SEARCH_DELAY_MS, useDebounced } from '../../useDebounced';

const SORTS = ['-updated_at', '-created_at', 'priority', 'display_number', 'subject'] as const;
const PRIORITIES = ['p1', 'p2', 'p3', 'p4'] as const;
const DEFAULT_VIEW = 'open';
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
 * Incidents (REQ-INC-104/105/110): built-in views with live counts, search by subject or ID,
 * filter by priority, sort, cursor paging; live (REQ-WI-005). A view never hides records
 * silently (Area 15): the page says which view is active and how many records it leaves out.
 */
export function IncidentsPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const dates = useDateTime();
  const { can } = useAccess();
  const allowed = can('incidents.view');
  const [mode, setMode] = useState<'current' | 'trash'>('current');
  const [view, setView] = useState<string>(DEFAULT_VIEW);
  const [search, setSearch] = useState('');
  const [priority, setPriority] = useState<string>();
  // One custom field filter (WP-026, REQ-INC-014 AC1): a pick list or yes/no field and a value.
  const [customKey, setCustomKey] = useState<string>();
  const [customValue, setCustomValue] = useState<string>();
  const [sort, setSort] = useState<string>('-updated_at');
  const text = useDebounced(search.trim(), SEARCH_DELAY_MS);
  const customFields = useCustomFields('incident', false, allowed);
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
  const filter = useMemo(
    () =>
      allOf(
        searchOf(text),
        priority === undefined ? undefined : { field: 'priority', op: 'eq', value: priority },
        customCondition,
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the condition is derived from these
    [text, priority, customField?.key, customField?.field_type, customValue],
  );
  const trash = mode === 'trash';
  const list = useIncidents({ view, filter, sort, limit: 50, trash }, allowed);
  const views = useIncidentViews(allowed && !trash);
  // Counter views say what they leave out like the built-in ones (Area 15; QA BUG-06).
  const counters = useIncidentCounters(allowed && !trash);
  const catalogue = useIncidentCatalogue(allowed);
  const { locale } = useAppearance();
  const groups = useUnits('groups', allowed);
  const groupNames = new Map((groups.data ?? []).map((g) => [g.id, g.name]));

  const queryClient = useQueryClient();
  useListChannel(allowed ? 'incidents' : null, (message) => {
    refreshList(queryClient, [...queryKeys.incidents.all, 'list']);
    refreshList(queryClient, queryKeys.incidents.views);
    refreshList(queryClient, queryKeys.incidents.counters);
    for (const id of message.ids) {
      refreshRecord(queryClient, queryKeys.incidents.detail(id), message);
    }
  });

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

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Flex justify="space-between" align="center" wrap gap={12}>
        <Typography.Title level={1} style={{ margin: 0 }}>
          {t('incidents.title')}
        </Typography.Title>
        <Space wrap>
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
      {!trash && <PersonalCounters active={view} onOpen={setView} />}
      <Flex gap={12} wrap>
        {!trash && (
          <Select
            aria-label={t('incidents.view')}
            prefix={`${t('incidents.view')}:`}
            value={view}
            onChange={setView}
            options={[
              ...(views.data ?? [{ view: DEFAULT_VIEW, count: 0, capped: false }]).map((v) => ({
                value: v.view,
                label: `${t(`work_item_view.${v.view}`)} (${String(v.count)}${v.capped ? '+' : ''})`,
              })),
              // A personal counter opened its view (REQ-INC-128 AC2): name it like the others.
              ...((COUNTERS as readonly string[]).includes(view)
                ? [{ value: view, label: t(`work_item_view.${view}`) }]
                : []),
            ]}
            style={{ minWidth: 'min(260px, 100%)' }}
            data-testid="inc-view"
          />
        )}
        <Input.Search
          allowClear
          aria-label={t('incidents.search')}
          placeholder={t('incidents.search')}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
          }}
          style={{ maxWidth: 320, minWidth: 0 }}
          data-testid="inc-search"
        />
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
              options={filterable.map((f) => ({ value: f.key, label: fieldName(f, locale) }))}
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
          onChange={setSort}
          options={SORTS.map((s) => ({ value: s, label: t(`incidents.sort.${s}`) }))}
          style={{ minWidth: 'min(220px, 100%)' }}
          data-testid="inc-sort"
        />
      </Flex>
      {!trash && (
        <ViewNotice
          view={view}
          inView={counts.get(view)?.count}
          everything={counts.get('all')}
          filtered={filter !== undefined}
          shown={total}
          onShowAll={() => {
            setView('all');
          }}
        />
      )}
      <Table<IncidentListItem>
        rowKey="id"
        data-testid="inc-table"
        loading={list.isPending && list.fetchStatus === 'fetching'}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 'max-content' }}
        locale={{
          emptyText: (
            <EmptyText>{t(trash ? 'incidents.trash_empty' : 'incidents.empty')}</EmptyText>
          ),
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
          { key: 'id', title: t('incidents.col.id'), render: (_, row) => row.display_id },
          {
            key: 'subject',
            title: t('work_item.field.subject'),
            // Long subjects are cut so the other columns stay in view (QA BUG-16); the whole
            // subject is the tooltip, and it reads in its own direction (QA BUG-12).
            width: 360,
            ellipsis: true,
            render: (_, row) => (
              <bdi dir="auto" title={row.subject}>
                {row.subject}
              </bdi>
            ),
          },
          {
            key: 'requester',
            title: t('work_item.field.requester_id'),
            render: (_, row) => personName(people, row.requester_id),
          },
          {
            key: 'status',
            title: t('work_item.field.status'),
            render: (_, row) => <StatusTag status={row.status} catalogue={catalogue.data} />,
          },
          {
            key: 'priority',
            title: t('work_item.field.priority'),
            render: (_, row) => (
              <PriorityTag priority={row.priority} source={row.priority_source} />
            ),
          },
          {
            key: 'group',
            title: t('work_item.field.group_id'),
            render: (_, row) => (row.group_id === null ? '' : (groupNames.get(row.group_id) ?? '')),
          },
          {
            key: 'technician',
            title: t('work_item.field.technician_id'),
            render: (_, row) => personName(people, row.technician_id),
          },
          {
            key: 'due',
            title: t('incidents.col.due'),
            render: (_, row) => (
              <SlaTag
                policyId={row.sla_policy_id}
                dueAt={row.resolution_due_at}
                format={dates.format}
              />
            ),
          },
          {
            key: 'updated',
            title: t('incidents.col.updated'),
            render: (_, row) => (
              <Tooltip title={dates.format(row.updated_at)}>
                <span>{dates.relative(row.updated_at)}</span>
              </Tooltip>
            ),
          },
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
    </Space>
  );
}

/**
 * Which view is active and what it leaves out (Area 15: no silent hiding). "Everything" counts
 * all incidents the user may see; the difference is what the view (plus search) does not show.
 */
function ViewNotice({
  view,
  inView,
  everything,
  filtered,
  shown,
  onShowAll,
}: {
  view: string;
  inView: number | undefined;
  everything: { count: number; capped: boolean } | undefined;
  filtered: boolean;
  shown: number | null;
  onShowAll: () => void;
}) {
  const t = useLabel();
  if (inView === undefined || everything === undefined) return null;
  const name = t(`work_item_view.${view}`);
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
  return (
    <WriteButton
      size="small"
      loading={restore.isPending}
      data-testid={`inc-restore-${row.display_id}`}
      onClick={() => {
        restore.mutate(
          { id: row.id, version: row.version },
          {
            onSuccess: () => void message.success(t('incidents.restored')),
            onError: reportError,
          },
        );
      }}
    >
      {t('incidents.restore')}
    </WriteButton>
  );
}
