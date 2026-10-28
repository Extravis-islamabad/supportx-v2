import { useQueryClient } from '@tanstack/react-query';
import {
  App,
  Button,
  Flex,
  Input,
  Segmented,
  Select,
  Space,
  Switch,
  Table,
  Typography,
} from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';

import {
  allOf,
  queryKeys,
  useAnnouncementSettings,
  useAnnouncements,
  useRestoreAnnouncement,
  useUpdateAnnouncementSettings,
  type AnnouncementListItem,
  type AnnouncementSettings,
  type FilterExpression,
} from '@supportx/api-client';
import { refreshList, refreshRecord, useListChannel, useTenantChannel } from '@supportx/realtime';
import {
  ConflictDialog,
  EmptyText,
  NoAccess,
  reportError,
  useAccess,
  useAppearance,
  useConflict,
  useLabel,
  useRefetchAfter,
  WriteButton,
} from '@supportx/ui';

import { SEVERITIES } from './form';
import { SeverityTag, StatusTag, VisibilityTag } from './tags';

const STATUSES = ['draft', 'published', 'archived'] as const;
const SORTS = ['-updated_at', 'title', '-published_at', '-created_at'] as const;
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

const equals = (field: string, value: string | undefined): FilterExpression | undefined =>
  value === undefined ? undefined : { field, op: 'eq', value };

/**
 * Announcements (staff): filter by status and severity, search titles, sort; live (WP-011) and
 * on the clock (a scheduled one turns live at its start without a reload, WP-012).
 */
export function AnnouncementsPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const allowed = can('announcements.view');
  const [view, setView] = useState<'current' | 'trash'>('current');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<string>();
  const [severity, setSeverity] = useState<string>();
  const [sort, setSort] = useState<string>('-updated_at');
  const text = useDebounced(search.trim(), SEARCH_DELAY_MS);
  const filter = useMemo(
    () =>
      allOf(
        text === '' ? undefined : { field: 'title', op: 'contains', value: text },
        equals('status', status),
        equals('severity', severity),
      ),
    [text, status, severity],
  );
  const trash = view === 'trash';
  const list = useAnnouncements({ filter, sort, limit: 50, trash }, allowed);

  const queryClient = useQueryClient();
  const refresh = () => {
    refreshList(queryClient, [...queryKeys.announcements.all, 'list']);
  };
  useListChannel(allowed ? 'announcements' : null, (message) => {
    refresh();
    for (const id of message.ids) {
      refreshRecord(queryClient, queryKeys.announcements.detail(id), message);
    }
  });
  useTenantChannel((message) => {
    if (message.type === 'refresh') refresh();
  });
  const firstPage = list.data?.pages[0];
  useRefetchAfter(firstPage?.next_change_in_seconds, list.dataUpdatedAt, refresh);

  const rows = useMemo(() => list.data?.pages.flatMap((page) => page.items) ?? [], [list.data]);
  if (!allowed) return <NoAccess titleKey="nav.announcements" />;
  const dateFormat = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });
  const any = { value: '', label: t('users.any') };

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Flex justify="space-between" align="center" wrap gap={12}>
        <Typography.Title level={1} style={{ margin: 0 }}>
          {t('announcements.title')}
        </Typography.Title>
        <Space wrap>
          <Segmented<'current' | 'trash'>
            value={view}
            onChange={(value) => {
              setView(value);
            }}
            options={[
              { value: 'current', label: t('announcements.current') },
              { value: 'trash', label: t('announcements.trash') },
            ]}
            data-testid="ann-view"
          />
          {can('announcements.manage') && (
            <WriteButton
              type="primary"
              onClick={() => void navigate('/announcements/new')}
              data-testid="ann-new"
            >
              {t('announcements.new')}
            </WriteButton>
          )}
        </Space>
      </Flex>
      {can('settings.manage') && <FourEyesSetting />}
      <Flex gap={12} wrap>
        <Input.Search
          allowClear
          aria-label={t('announcements.search')}
          placeholder={t('announcements.search')}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
          }}
          style={{ maxWidth: 320 }}
          data-testid="ann-search"
        />
        <Select
          aria-label={t('announcement.field.status')}
          prefix={`${t('announcement.field.status')}:`}
          value={status ?? ''}
          onChange={(value) => {
            setStatus(value === '' ? undefined : value);
          }}
          options={[
            any,
            ...STATUSES.map((value) => ({ value, label: t(`announcement_status.${value}`) })),
          ]}
          style={{ minWidth: 180 }}
          data-testid="ann-filter-status"
        />
        <Select
          aria-label={t('announcement.field.severity')}
          prefix={`${t('announcement.field.severity')}:`}
          value={severity ?? ''}
          onChange={(value) => {
            setSeverity(value === '' ? undefined : value);
          }}
          options={[
            any,
            ...SEVERITIES.map((value) => ({ value, label: t(`announcement_severity.${value}`) })),
          ]}
          style={{ minWidth: 180 }}
          data-testid="ann-filter-severity"
        />
        <Select
          aria-label={t('users.sort')}
          prefix={`${t('users.sort')}:`}
          value={sort}
          onChange={setSort}
          options={SORTS.map((value) => ({ value, label: t(`announcements.sort.${value}`) }))}
          style={{ minWidth: 220 }}
          data-testid="ann-sort"
        />
      </Flex>
      <Table<AnnouncementListItem>
        rowKey="id"
        data-testid="ann-table"
        loading={list.isPending && list.fetchStatus === 'fetching'}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: <EmptyText>{t('announcements.empty')}</EmptyText> }}
        onRow={(row) =>
          trash
            ? { 'data-testid': `ann-row-${row.display_id}` }
            : {
                onClick: () => void navigate(`/announcements/${row.id}`),
                style: { cursor: 'pointer' },
                'data-testid': `ann-row-${row.display_id}`,
              }
        }
        columns={[
          { key: 'id', title: t('announcements.col.id'), render: (_, row) => row.display_id },
          { key: 'title', title: t('announcement.field.title'), render: (_, row) => row.title },
          {
            key: 'severity',
            title: t('announcement.field.severity'),
            render: (_, row) => <SeverityTag severity={row.severity} />,
          },
          {
            key: 'status',
            title: t('announcement.field.status'),
            render: (_, row) => (
              <Space size={4} wrap>
                <StatusTag status={row.status} />
                {row.status === 'published' && <VisibilityTag visibility={row.visibility} />}
              </Space>
            ),
          },
          {
            key: 'audience',
            title: t('announcement.field.audience'),
            render: (_, row) => t(`announcement_audience.${row.audience}`),
          },
          {
            key: 'updated',
            title: t('announcements.col.updated'),
            render: (_, row) => dateFormat.format(new Date(row.updated_at)),
          },
          ...(trash
            ? [
                {
                  key: 'restore',
                  title: '',
                  render: (_: unknown, row: AnnouncementListItem) => <RestoreButton row={row} />,
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
            data-testid="ann-more"
          >
            {t('announcements.more')}
          </Button>
        </Flex>
      )}
    </Space>
  );
}

function RestoreButton({ row }: { row: AnnouncementListItem }) {
  const t = useLabel();
  const { message } = App.useApp();
  const restore = useRestoreAnnouncement();
  // Changed by someone after the list showed it (409): the shared dialog names who and what
  // (announcements keep field history); "Keep my changes" restores it anyway.
  const conflict = useConflict();
  const run = (version: number) => {
    restore.mutate(
      { id: row.id, version },
      {
        onSuccess: () => void message.success(t('announcements.restored')),
        onError: (error) => {
          if (!conflict.take(error)) reportError(error);
        },
      },
    );
  };
  return (
    <>
      <WriteButton
        size="small"
        loading={restore.isPending}
        data-testid={`ann-restore-${row.display_id}`}
        onClick={() => {
          run(row.version);
        }}
      >
        {t('announcements.restore')}
      </WriteButton>
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={(field) => t(`announcement.field.${field}`)}
        onReload={conflict.clear}
        onKeepMine={() => {
          conflict.clear();
          if (conflict.latestVersion !== undefined) run(conflict.latestVersion);
        }}
      />
    </>
  );
}

/** The tenant's four-eyes rule (settings.manage): the author or owner may not publish. */
function FourEyesSetting() {
  const t = useLabel();
  const { message } = App.useApp();
  const settings = useAnnouncementSettings();
  const update = useUpdateAnnouncementSettings();
  const queryClient = useQueryClient();
  useTenantChannel((event) => {
    if (event.type === 'announcements.settings_changed' || event.type === 'refresh') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.announcements.settings });
    }
  });
  // The rule as it was when switched, and the switch someone else beat (409): the shared dialog.
  const conflict = useConflict();
  const [tried, setTried] = useState<{ checked: boolean; opened: AnnouncementSettings }>();
  const change = (checked: boolean, version: number, opened: AnnouncementSettings) => {
    update.mutate(
      { requireSecond: checked, version },
      {
        onSuccess: () => void message.success(t('announcements.settings_saved')),
        onError: (error) => {
          if (conflict.take(error)) setTried({ checked, opened });
          else reportError(error);
        },
      },
    );
  };
  const view = (rule: AnnouncementSettings | undefined) =>
    rule && { require_second_publisher: rule.require_second_publisher };
  const dialog = (
    <ConflictDialog
      open={conflict.open}
      error={conflict.error}
      fieldLabel={() => t('announcements.four_eyes')}
      opened={view(tried?.opened)}
      latest={view(settings.data)}
      onReload={() => {
        conflict.clear();
        setTried(undefined);
      }}
      onKeepMine={() => {
        conflict.clear();
        if (tried !== undefined && settings.data !== undefined) {
          change(tried.checked, conflict.latestVersion ?? settings.data.version, settings.data);
        }
        setTried(undefined);
      }}
    />
  );
  if (settings.data === undefined) return dialog;
  const current = settings.data;
  const { require_second_publisher: on, version } = current;
  return (
    <Flex gap={8} align="center">
      <Switch
        id="four-eyes"
        checked={on}
        loading={update.isPending}
        data-testid="ann-four-eyes"
        onChange={(checked) => {
          change(checked, version, current);
        }}
      />
      <label htmlFor="four-eyes">
        <Typography.Text>{t('announcements.four_eyes')}</Typography.Text>{' '}
        <Typography.Text type="secondary">{t('announcements.four_eyes_help')}</Typography.Text>
      </label>
      {dialog}
    </Flex>
  );
}
