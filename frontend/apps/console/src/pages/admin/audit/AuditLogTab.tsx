import { useQuery } from '@tanstack/react-query';
import { Button, Flex, Input, Modal, Select, Space, Table, Tag, Tooltip, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';

import {
  api,
  call,
  useAuditEntries,
  useAuditSavedSearches,
  useAuditSavedSearchMutations,
  useUsers,
  type AuditEntriesQuery,
  type AuditEntry,
  type FilterExpression,
} from '@supportx/api-client';
import { en } from '@supportx/labels';
import { useListChannel } from '@supportx/realtime';
import { FormProblem, useDateTime, useFormProblem, useLabel, lengthLimit } from '@supportx/ui';

import { AuditEntryDrawer } from './AuditEntryDrawer';
import { actorLabel, objectLabel, OUTCOME_COLOURS } from './present';
import { StateTag } from './StateTag';

/** Every action code that has a label (the catalogue lives in the backend; labels mirror it). */
const ACTIONS = Object.keys(en)
  .filter((key) => key.startsWith('audit.action.'))
  .map((key) => key.slice('audit.action.'.length));
const RANGES = ['today', '7d', '30d', 'this_month', 'last_month', 'all'] as const;
const CATEGORIES = [
  'session',
  'access',
  'organisation',
  'configuration',
  'records',
  'security',
  'data',
  'licence',
  'reads',
] as const;
const OUTCOMES = ['done', 'refused', 'failed'] as const;
const ACTOR_TYPES = [
  'person',
  'service_account',
  'api_key',
  'ai_agent',
  'automation',
  'system',
  'vendor_support',
] as const;
const CLIENTS = ['console', 'portal', 'mobile', 'api', 'worker'] as const;
const FILTER_KEYS = ['range', 'action', 'category', 'outcome', 'actor_type', 'actor_id', 'client'];

function rangeFilter(range: string | undefined): FilterExpression | undefined {
  switch (range) {
    case 'today':
      return { field: 'occurred_at', op: 'today', value: null };
    case '7d':
      return { field: 'occurred_at', op: 'last_n_days', value: 7 };
    case '30d':
      return { field: 'occurred_at', op: 'last_n_days', value: 30 };
    case 'this_month':
      return { field: 'occurred_at', op: 'this_month', value: null };
    case 'last_month':
      return { field: 'occurred_at', op: 'last_month', value: null };
    default:
      return undefined;
  }
}

/**
 * The audit log (REQ-AUD-003, 007): filters by actor, actor type, action, category, outcome,
 * client and time range; saved searches; paging without a limit. New entries never move the rows
 * under the pointer: they are announced in a pill and shown when the reader asks (REQ-WI-012).
 */
export function AuditLogTab() {
  const t = useLabel();
  const dates = useDateTime();
  const [params, setParams] = useSearchParams();
  const filters = Object.fromEntries(
    FILTER_KEYS.flatMap((key) => {
      const value = params.get(key);
      return value === null || value === '' ? [] : [[key, value]];
    }),
  ) as Record<string, string>;
  const { range, ...simple } = filters;
  const searchKey = params.toString();
  const query: AuditEntriesQuery = useMemo(
    () => ({ params: simple, filter: rangeFilter(range ?? '30d') }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the URL (searchKey) is the source of truth
    [searchKey],
  );
  const entries = useAuditEntries(query);
  const rows = useMemo(() => entries.data?.pages.flatMap((p) => p.items) ?? [], [entries.data]);
  const top = rows[0]?.id;

  // Live (REQ-AUD-007 AC3): check the head of the list; new rows are announced, not inserted.
  const head = useQuery({
    queryKey: ['audit', 'head', query],
    queryFn: () =>
      call(
        api.GET('/api/v1/audit/entries', {
          params: {
            query: {
              ...query.params,
              filter: query.filter === undefined ? undefined : JSON.stringify(query.filter),
              limit: 50,
            },
          },
        }),
      ),
    enabled: false,
  });
  const fresh = useMemo(() => {
    const items = head.data?.items ?? [];
    if (top === undefined) return items.length;
    const index = items.findIndex((item) => item.id === top);
    return index === -1 ? items.length : index;
  }, [head.data, top]);
  useListChannel('audit', () => {
    void head.refetch().then((result) => {
      const index = (result.data?.items ?? []).findIndex((item) => item.id === top);
      // Only sealing or status moved: refresh in place (the rows keep their order).
      if (index === 0) void entries.refetch();
    });
  });

  const setFilter = (key: string, value: string | undefined) => {
    const next = new URLSearchParams(params);
    if (value === undefined || value === '') next.delete(key);
    else next.set(key, value);
    next.delete('entry');
    setParams(next);
  };
  const open = (id: string | undefined) => {
    const next = new URLSearchParams(params);
    if (id === undefined) next.delete('entry');
    else next.set('entry', id);
    setParams(next);
  };

  const any = { value: '', label: t('audit.ui.any') };
  const option = (prefix: string) => (value: string) => ({
    value,
    label: t(`${prefix}.${value}`),
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Flex gap={8} wrap align="center">
        <Select
          aria-label={t('audit.ui.filter.range')}
          prefix={`${t('audit.ui.filter.range')}:`}
          value={range ?? '30d'}
          onChange={(value) => {
            setFilter('range', value);
          }}
          options={RANGES.map(option('audit.ui.range'))}
          style={{ minWidth: 200 }}
          data-testid="audit-filter-range"
        />
        <PersonFilter
          value={filters.actor_id}
          onChange={(value) => {
            setFilter('actor_id', value);
          }}
        />
        <Select
          aria-label={t('audit.ui.filter.action')}
          prefix={`${t('audit.ui.filter.action')}:`}
          showSearch
          optionFilterProp="label"
          value={filters.action ?? ''}
          onChange={(value) => {
            setFilter('action', value);
          }}
          options={[any, ...ACTIONS.map(option('audit.action'))]}
          style={{ minWidth: 260 }}
          data-testid="audit-filter-action"
        />
        {(
          [
            ['category', CATEGORIES, 'audit_category'],
            ['outcome', OUTCOMES, 'audit_outcome'],
            ['actor_type', ACTOR_TYPES, 'audit_actor_type'],
            ['client', CLIENTS, 'audit_client'],
          ] as const
        ).map(([key, values, prefix]) => (
          <Select
            key={key}
            aria-label={t(`audit.ui.filter.${key}`)}
            prefix={`${t(`audit.ui.filter.${key}`)}:`}
            value={filters[key] ?? ''}
            onChange={(value) => {
              setFilter(key, value);
            }}
            options={[any, ...values.map(option(prefix))]}
            style={{ minWidth: 180 }}
            data-testid={`audit-filter-${key}`}
          />
        ))}
        <SavedSearches
          current={filters}
          onApply={(saved) => {
            const next = new URLSearchParams(saved);
            next.set('tab', 'log');
            setParams(next);
          }}
        />
      </Flex>
      <div style={{ minHeight: 32 }}>
        {fresh > 0 && (
          <Button
            type="primary"
            shape="round"
            size="small"
            data-testid="audit-new-entries"
            onClick={() => {
              void entries.refetch();
            }}
          >
            {t('audit.ui.new_entries', { count: fresh })}
          </Button>
        )}
      </div>
      <Table<AuditEntry>
        rowKey="id"
        data-testid="audit-table"
        size="small"
        loading={entries.isPending}
        dataSource={rows}
        pagination={false}
        onRow={(entry) => ({
          onClick: () => {
            open(entry.id);
          },
          style: { cursor: 'pointer' },
          'data-testid': `audit-row-${entry.id}`,
        })}
        columns={[
          {
            key: 'time',
            title: t('audit.ui.col.time'),
            render: (_, entry) => (
              <time dateTime={entry.occurred_at}>{dates.formatExact(entry.occurred_at)}</time>
            ),
          },
          { key: 'actor', title: t('audit.ui.col.actor'), render: (_, e) => actorLabel(t, e) },
          {
            key: 'action',
            title: t('audit.ui.col.action'),
            render: (_, entry) => t(`audit.action.${entry.action}`),
          },
          { key: 'object', title: t('audit.ui.col.object'), render: (_, e) => objectLabel(t, e) },
          {
            key: 'outcome',
            title: t('audit.ui.col.outcome'),
            render: (_, entry) => (
              <StateTag tone={OUTCOME_COLOURS[entry.outcome]}>
                {t(`audit_outcome.${entry.outcome}`)}
              </StateTag>
            ),
          },
          {
            key: 'client',
            title: t('audit.ui.col.client'),
            render: (_, entry) => t(`audit_client.${entry.client}`),
          },
          {
            key: 'seal',
            title: t('audit.ui.col.seal'),
            render: (_, entry) =>
              entry.seq === null ? (
                <Tooltip title={t('audit.ui.pending_seal_help')}>
                  <Tag data-testid="audit-pending-seal">{t('audit.pending_seal')}</Tag>
                </Tooltip>
              ) : (
                <Typography.Text type="secondary">
                  {t('audit.ui.sealed_at_position', { seq: entry.seq })}
                </Typography.Text>
              ),
          },
        ]}
      />
      <Flex justify="center">
        {entries.hasNextPage ? (
          <Button
            loading={entries.isFetchingNextPage}
            onClick={() => {
              void entries.fetchNextPage();
            }}
            data-testid="audit-load-more"
          >
            {t('audit.ui.load_more')}
          </Button>
        ) : (
          rows.length > 0 && <Typography.Text type="secondary">{t('audit.ui.end')}</Typography.Text>
        )}
      </Flex>
      <AuditEntryDrawer
        id={params.get('entry') ?? undefined}
        onClose={() => {
          open(undefined);
        }}
      />
    </Space>
  );
}

function PersonFilter({
  value,
  onChange,
}: {
  value: string | undefined;
  onChange: (value: string | undefined) => void;
}) {
  const t = useLabel();
  const [search, setSearch] = useState('');
  const people = useUsers({
    filter:
      search === ''
        ? undefined
        : {
            or: [
              { field: 'display_name', op: 'contains', value: search },
              { field: 'email', op: 'contains', value: search },
            ],
          },
    limit: 20,
  });
  const options = (people.data?.pages[0]?.items ?? []).map((user) => ({
    value: user.id,
    label: user.email === null ? user.display_name : `${user.display_name} · ${user.email}`,
  }));
  return (
    <Select
      aria-label={t('audit.ui.filter.person')}
      prefix={`${t('audit.ui.filter.person')}:`}
      allowClear
      showSearch
      filterOption={false}
      onSearch={setSearch}
      value={value}
      onChange={(next: string | undefined) => {
        onChange(next);
      }}
      options={options}
      placeholder={t('audit.ui.any')}
      style={{ minWidth: 240 }}
      data-testid="audit-filter-person"
    />
  );
}

function SavedSearches({
  current,
  onApply,
}: {
  current: Record<string, string>;
  onApply: (query: Record<string, string>) => void;
}) {
  const t = useLabel();
  const saved = useAuditSavedSearches();
  const { save, remove } = useAuditSavedSearchMutations();
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState('');
  // A refused save is shown in the naming dialog; it was not shown at all (QA WP-029 BUG-02).
  const problem = useFormProblem();
  const items = saved.data ?? [];
  return (
    <>
      <Select
        aria-label={t('audit.ui.saved.choose')}
        placeholder={t('audit.ui.saved.choose')}
        value={null}
        onChange={(id: string) => {
          const found = items.find((item) => item.id === id);
          if (found !== undefined) onApply(found.query);
        }}
        options={items.map((item) => ({ value: item.id, label: item.name }))}
        style={{ minWidth: 200 }}
        data-testid="audit-saved-select"
        notFoundContent={t('audit.ui.saved.none')}
      />
      <Button
        onClick={() => {
          setName('');
          setNaming(true);
        }}
        data-testid="audit-saved-save"
      >
        {t('audit.ui.saved.save')}
      </Button>
      {items.length > 0 && (
        <Select
          aria-label={t('audit.ui.saved.delete')}
          placeholder={t('audit.ui.saved.delete')}
          value={null}
          onChange={(id: string) => {
            remove.mutate(id);
          }}
          options={items.map((item) => ({ value: item.id, label: item.name }))}
          style={{ minWidth: 160 }}
        />
      )}
      <Modal
        open={naming}
        title={t('audit.ui.saved.save')}
        okText={t('audit.ui.saved.save')}
        cancelText={t('audit.ui.cancel')}
        okButtonProps={{ disabled: name.trim() === '', loading: save.isPending }}
        onCancel={() => {
          setNaming(false);
          problem.clear();
        }}
        onOk={() => {
          problem.clear();
          save.mutate(
            { name: name.trim(), query: current },
            {
              onSuccess: () => {
                setNaming(false);
              },
              onError: problem.show,
            },
          );
        }}
      >
        <FormProblem problem={problem} />
        <Input
          aria-label={t('audit.ui.saved.name')}
          placeholder={t('audit.ui.saved.name')}
          value={name}
          count={lengthLimit(100)}
          onChange={(event) => {
            setName(event.target.value);
          }}
          data-testid="audit-saved-name"
        />
      </Modal>
    </>
  );
}
