import { PlusOutlined, UploadOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Badge, Button, Flex, Input, Select, Space, Spin, Table, Typography } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';

import {
  allOf,
  queryKeys,
  useStructure,
  useUsers,
  type FilterExpression,
  type UserDetail,
} from '@supportx/api-client';
import { refreshList, refreshRecord, useListChannel } from '@supportx/realtime';
import { NoAccess, ToneTag, useAccess, useAppearance, useLabel } from '@supportx/ui';

import { UserAccessDrawer } from './UserAccessDrawer';
import { ImportDrawer } from './people/ImportDrawer';
import { PersonDrawer } from './people/PersonDrawer';
import { SEARCH_DELAY_MS, useDebounced } from '../../useDebounced';

const SORTS = ['display_name', '-display_name', '-last_login_at', '-created_at'] as const;
/** Saved people views (WP-021, REQ-ADM-001): each a fixed filter. */
const VIEWS = {
  all: undefined,
  active: { field: 'status', op: 'eq', value: 'active' },
  technicians: {
    and: [
      { field: 'user_type', op: 'eq', value: 'technician' },
      { field: 'status', op: 'eq', value: 'active' },
    ],
  },
  requesters: {
    and: [
      { field: 'user_type', op: 'eq', value: 'requester' },
      { field: 'status', op: 'eq', value: 'active' },
    ],
  },
  contacts: { field: 'can_sign_in', op: 'eq', value: false },
  vip: { field: 'vip', op: 'eq', value: true },
  deactivated: { field: 'status', op: 'eq', value: 'disabled' },
} as const satisfies Record<string, FilterExpression | undefined>;
type View = keyof typeof VIEWS;

function equals(field: string, value: string | undefined): FilterExpression | undefined {
  return value === undefined ? undefined : { field, op: 'eq', value };
}

/**
 * Admin › People: GET /users with the filter DSL (views, site, department, search), server-side
 * sort and cursor pagination, loading the next page when the end of the list scrolls into view.
 * Admins add, edit and import people here (WP-021).
 */
export function UsersPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const allowed = can('users.view');
  const manage = can('users.manage');
  const [opened, setOpened] = useState<UserDetail>();
  const [editing, setEditing] = useState<string>();
  const [importing, setImporting] = useState(false);
  const [search, setSearch] = useState('');
  const [view, setView] = useState<View>('active');
  const [siteId, setSiteId] = useState<string>();
  const [departmentId, setDepartmentId] = useState<string>();
  // Only the filters use these: if they fail, the filters are just empty (no second toast).
  const sites = useStructure('sites', allowed && can('sites.view'), true);
  const departments = useStructure('departments', allowed && can('departments.view'), true);
  const siteName = useMemo(
    () => new Map((sites.data ?? []).map((site) => [site.id, site.name])),
    [sites.data],
  );
  const departmentName = useMemo(
    () => new Map((departments.data ?? []).map((d) => [d.id, d.name])),
    [departments.data],
  );
  const [sort, setSort] = useState<string>('display_name');
  const query = useDebounced(search, SEARCH_DELAY_MS);

  const filter = useMemo(
    () => allOf(VIEWS[view], equals('site_id', siteId), equals('department_id', departmentId)),
    [view, siteId, departmentId],
  );
  // Names and emails, however they are typed (WP-027).
  const users = useUsers({ filter, q: query, sort, limit: 25 }, allowed);
  // Live (WP-011): a new or changed user refreshes the lists on screen and the changed records.
  const queryClient = useQueryClient();
  useListChannel(allowed ? 'users' : null, (message) => {
    refreshList(queryClient, [...queryKeys.users.all, 'list']);
    for (const id of message.ids) refreshRecord(queryClient, queryKeys.users.detail(id), message);
  });
  const rows = useMemo(() => users.data?.pages.flatMap((page) => page.items) ?? [], [users.data]);
  const total = users.data?.pages[0]?.estimated_total;

  // Infinite scroll: fetch the next page when the sentinel below the table becomes visible.
  const sentinel = useRef<HTMLDivElement>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = users;
  useEffect(() => {
    const node = sentinel.current;
    if (node === null || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting) && hasNextPage && !isFetchingNextPage) {
        void fetchNextPage();
      }
    });
    observer.observe(node);
    return () => {
      observer.disconnect();
    };
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  if (!allowed) return <NoAccess titleKey="nav.admin_users" />;

  const dateFormat = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });
  const anyOption = { value: '', label: t('users.any') };

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Flex justify="space-between" align="baseline" wrap>
        <Typography.Title level={2} style={{ margin: 0 }}>
          {t('people.title')}
        </Typography.Title>
        <Flex gap={12} align="baseline" wrap>
          {total !== undefined && total !== null && (
            <Typography.Text type="secondary" data-testid="users-total">
              {t('people.total', { count: total })}
            </Typography.Text>
          )}
          {manage && (
            <>
              <Button
                icon={<UploadOutlined />}
                onClick={() => {
                  setImporting(true);
                }}
                data-testid="people-import"
              >
                {t('people.import')}
              </Button>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => {
                  setEditing('new');
                }}
                data-testid="people-add"
              >
                {t('people.add')}
              </Button>
            </>
          )}
        </Flex>
      </Flex>
      <Flex gap={12} wrap>
        <Input.Search
          allowClear
          aria-label={t('users.search')}
          placeholder={t('users.search')}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
          }}
          style={{ maxWidth: 320 }}
          data-testid="users-search"
        />
        <Select
          aria-label={t('people.view')}
          data-testid="users-view"
          value={view}
          onChange={setView}
          options={(Object.keys(VIEWS) as View[]).map((value) => ({
            value,
            label: t(`people.view.${value}`),
          }))}
          style={{ minWidth: 200 }}
          prefix={`${t('people.view')}:`}
        />
        <Select
          aria-label={t('people.field.site')}
          data-testid="users-filter-site"
          value={siteId ?? ''}
          onChange={(value) => {
            setSiteId(value === '' ? undefined : value);
          }}
          options={[
            anyOption,
            ...(sites.data ?? []).map((site) => ({ value: site.id, label: site.name })),
          ]}
          style={{ minWidth: 180 }}
          prefix={`${t('people.field.site')}:`}
        />
        <Select
          aria-label={t('people.field.department')}
          data-testid="users-filter-department"
          value={departmentId ?? ''}
          onChange={(value) => {
            setDepartmentId(value === '' ? undefined : value);
          }}
          options={[
            anyOption,
            ...(departments.data ?? []).map((d) => ({ value: d.id, label: d.name })),
          ]}
          style={{ minWidth: 180 }}
          prefix={`${t('people.field.department')}:`}
        />
        <Select
          aria-label={t('users.sort')}
          data-testid="users-sort"
          value={sort}
          onChange={setSort}
          options={SORTS.map((value) => ({ value, label: t(`users.sort.${value}`) }))}
          style={{ minWidth: 220 }}
          prefix={`${t('users.sort')}:`}
        />
      </Flex>
      <Table<UserDetail>
        rowKey="id"
        data-testid="users-table"
        loading={users.isPending && users.fetchStatus === 'fetching'}
        dataSource={rows}
        pagination={false}
        onRow={(user) => ({
          onClick: () => {
            if (manage) setEditing(user.id);
            else setOpened(user);
          },
          style: { cursor: 'pointer' },
          'data-testid': `user-row-${user.email ?? user.id}`,
        })}
        columns={[
          {
            key: 'name',
            title: t('users.col.name'),
            render: (_, user) => (
              <Flex gap={6} wrap align="center">
                <span>{user.display_name}</span>
                {user.vip && <ToneTag tone="purple">{t('people.vip')}</ToneTag>}
                {!user.can_sign_in && <ToneTag tone="default">{t('people.contact')}</ToneTag>}
              </Flex>
            ),
          },
          {
            key: 'email',
            title: t('users.col.email'),
            render: (_, user) => <bdi>{user.email ?? '—'}</bdi>,
          },
          {
            key: 'site',
            title: t('people.field.site'),
            render: (_, user) => (user.site_id === null ? '' : (siteName.get(user.site_id) ?? '')),
          },
          {
            key: 'department',
            title: t('people.field.department'),
            render: (_, user) =>
              user.department_id === null ? '' : (departmentName.get(user.department_id) ?? ''),
          },
          {
            key: 'type',
            title: t('users.col.type'),
            render: (_, user) => t(`user_type.${user.user_type}`),
          },
          {
            key: 'status',
            title: t('users.col.status'),
            render: (_, user) => (
              <Badge
                status={user.status === 'active' ? 'success' : 'default'}
                text={t(`user_status.${user.status}`)}
              />
            ),
          },
          {
            key: 'last_login',
            title: t('users.col.last_login'),
            render: (_, user) =>
              user.last_login_at === null
                ? t('users.never')
                : dateFormat.format(new Date(user.last_login_at)),
          },
        ]}
      />
      <UserAccessDrawer
        user={opened}
        onClose={() => {
          setOpened(undefined);
        }}
      />
      <PersonDrawer
        userId={editing}
        onClose={() => {
          setEditing(undefined);
        }}
      />
      <ImportDrawer
        open={importing}
        onClose={() => {
          setImporting(false);
        }}
      />
      <div ref={sentinel} data-testid="users-sentinel" style={{ minHeight: 1 }}>
        {isFetchingNextPage && (
          <Flex justify="center" gap={8}>
            <Spin size="small" />{' '}
            <Typography.Text type="secondary">{t('users.loading_more')}</Typography.Text>
          </Flex>
        )}
        {!hasNextPage && rows.length > 0 && (
          <Typography.Text type="secondary" data-testid="users-end">
            {t('users.end')}
          </Typography.Text>
        )}
      </div>
    </Space>
  );
}
