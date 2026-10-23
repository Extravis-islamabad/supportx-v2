import { Badge, Flex, Input, Select, Space, Spin, Table, Typography } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';

import {
  allOf,
  searchFilter,
  useUsers,
  type FilterExpression,
  type UserDetail,
} from '@supportx/api-client';
import { NoAccess, useAccess, useAppearance, useLabel } from '@supportx/ui';

import { UserAccessDrawer } from './UserAccessDrawer';

const SORTS = ['display_name', '-display_name', '-last_login_at', '-created_at'] as const;
const TYPES = ['technician', 'requester'] as const;
const STATUSES = ['active', 'disabled'] as const;
const SEARCH_DELAY_MS = 300;

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(value);
    }, delay);
    return () => {
      clearTimeout(timer);
    };
  }, [value, delay]);
  return debounced;
}

function equals(field: string, value: string | undefined): FilterExpression | undefined {
  return value === undefined ? undefined : { field, op: 'eq', value };
}

/**
 * Admin › Users: GET /users with the filter DSL (search, type, status), server-side sort and
 * cursor pagination, loading the next page when the end of the list scrolls into view.
 */
export function UsersPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const allowed = can('users.view');
  const [opened, setOpened] = useState<UserDetail>();
  const [search, setSearch] = useState('');
  const [userType, setUserType] = useState<string>();
  const [status, setStatus] = useState<string>();
  const [sort, setSort] = useState<string>('display_name');
  const query = useDebounced(search, SEARCH_DELAY_MS);

  const filter = useMemo(
    () => allOf(searchFilter(query), equals('user_type', userType), equals('status', status)),
    [query, userType, status],
  );
  const users = useUsers({ filter, sort, limit: 25 }, allowed);
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
          {t('users.title')}
        </Typography.Title>
        {total !== undefined && total !== null && (
          <Typography.Text type="secondary" data-testid="users-total">
            {t('users.total', { count: total })}
          </Typography.Text>
        )}
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
          aria-label={t('users.filter_type')}
          data-testid="users-filter-type"
          value={userType ?? ''}
          onChange={(value) => {
            setUserType(value === '' ? undefined : value);
          }}
          options={[
            anyOption,
            ...TYPES.map((value) => ({ value, label: t(`user_type.${value}`) })),
          ]}
          style={{ minWidth: 160 }}
          prefix={`${t('users.filter_type')}:`}
        />
        <Select
          aria-label={t('users.filter_status')}
          data-testid="users-filter-status"
          value={status ?? ''}
          onChange={(value) => {
            setStatus(value === '' ? undefined : value);
          }}
          options={[
            anyOption,
            ...STATUSES.map((value) => ({ value, label: t(`user_status.${value}`) })),
          ]}
          style={{ minWidth: 160 }}
          prefix={`${t('users.filter_status')}:`}
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
            setOpened(user);
          },
          style: { cursor: 'pointer' },
          'data-testid': `user-row-${user.email}`,
        })}
        columns={[
          { key: 'name', title: t('users.col.name'), render: (_, user) => user.display_name },
          { key: 'email', title: t('users.col.email'), render: (_, user) => user.email },
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
