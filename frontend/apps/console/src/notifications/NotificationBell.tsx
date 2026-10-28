import { BellOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { App as AntApp, Badge, Button, Drawer, Empty, List, Space, Switch, Typography } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';

import {
  queryKeys,
  useMarkNotificationsRead,
  useNotificationPreferences,
  useNotifications,
  useSaveNotificationPreferences,
  type NotificationEntry,
} from '@supportx/api-client';
import { usePersonalChannel } from '@supportx/realtime';
import { reportError, useDateTime, useLabel } from '@supportx/ui';

/**
 * The notification centre (WP-023, REQ-INC-131): a bell with the unread count in the header and
 * a drawer with your entries grouped by day, newest first. Opening one opens its record and
 * marks it read; "Mark all read" clears the badge; do-not-disturb stops pop-ups and non-urgent
 * e-mail (entries still land here). Everything updates live from your personal channel: a new
 * entry raises the badge at once, reading on another device lowers it.
 */
export function NotificationBell() {
  const t = useLabel();
  const { message } = AntApp.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const centre = useNotifications();
  const preferences = useNotificationPreferences();
  const savePreferences = useSaveNotificationPreferences();
  const markRead = useMarkNotificationsRead();
  const { formatDay, relative, zone } = useDateTime();
  const items = useMemo(
    () => centre.data?.pages.flatMap((page) => page.items) ?? [],
    [centre.data],
  );
  const unread = centre.data?.pages[0]?.unread ?? 0;
  const quiet = preferences.data?.do_not_disturb ?? false;

  usePersonalChannel((event) => {
    if (event.type === 'notifications.created' || event.type === 'notifications.read') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.centre });
    } else if (event.type === 'notifications.preferences_changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.preferences });
    }
  });

  // A pop-up for an entry that arrived while you were here (never the ones already there).
  const newest = items[0]?.id;
  const seen = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (newest === undefined) return;
    const first = seen.current === undefined;
    if (!first && newest !== seen.current && !quiet && !open) {
      const entry = items[0];
      if (entry && !entry.read) void message.info(entry.title);
    }
    seen.current = newest;
  }, [newest, items, quiet, open, message]);

  const dayOf = useMemo(
    () => new Intl.DateTimeFormat('en-CA', { timeZone: zone, dateStyle: 'short' }),
    [zone],
  );
  const days = useMemo(() => {
    const groups = new Map<string, NotificationEntry[]>();
    for (const entry of items) {
      const day = dayOf.format(new Date(entry.created_at));
      groups.set(day, [...(groups.get(day) ?? []), entry]);
    }
    return [...groups.entries()];
  }, [items, dayOf]);

  const openEntry = (entry: NotificationEntry) => {
    if (!entry.read) markRead.mutate([entry.id], { onError: reportError });
    setOpen(false);
    void navigate(entry.link);
  };

  return (
    <>
      <Badge count={unread} size="small" overflowCount={99}>
        <Button
          type="text"
          icon={<BellOutlined />}
          aria-label={t('notifications.open', { count: unread })}
          onClick={() => {
            setOpen(true);
          }}
          data-testid="notifications-bell"
        />
      </Badge>
      <Drawer
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        title={t('notifications.title')}
        width={420}
        data-testid="notifications-drawer"
        extra={
          <Button
            size="small"
            disabled={unread === 0}
            loading={markRead.isPending}
            onClick={() => {
              markRead.mutate(undefined, { onError: reportError });
            }}
            data-testid="notifications-read-all"
          >
            {t('notifications.read_all')}
          </Button>
        }
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Space>
            <Switch
              checked={quiet}
              loading={preferences.isPending || savePreferences.isPending}
              disabled={preferences.data === undefined}
              aria-label={t('notifications.do_not_disturb')}
              onChange={(on) => {
                const current = preferences.data;
                if (current === undefined) return;
                savePreferences.mutate(
                  {
                    off: current.choices
                      .filter((c) => !c.on && !c.locked)
                      .map((c) => ({ category: c.category, channel: c.channel })),
                    doNotDisturb: on,
                    version: current.version,
                  },
                  { onError: reportError },
                );
              }}
              data-testid="notifications-dnd"
            />
            <Typography.Text>{t('notifications.do_not_disturb')}</Typography.Text>
          </Space>
          {items.length === 0 && !centre.isPending ? (
            <Empty description={t('notifications.empty')} data-testid="notifications-empty" />
          ) : (
            days.map(([day, entries]) => (
              <div key={day}>
                <Typography.Title level={5} style={{ marginTop: 0 }}>
                  {formatDay(day)}
                </Typography.Title>
                <List
                  dataSource={entries}
                  rowKey="id"
                  renderItem={(entry) => (
                    <List.Item
                      onClick={() => {
                        openEntry(entry);
                      }}
                      style={{ cursor: 'pointer' }}
                      data-testid="notification-item"
                      data-read={entry.read ? 'true' : 'false'}
                    >
                      <List.Item.Meta
                        avatar={entry.read ? undefined : <Badge status="processing" />}
                        title={
                          <Typography.Text strong={!entry.read}>
                            <a
                              href={entry.link}
                              onClick={(event) => {
                                event.preventDefault();
                              }}
                            >
                              {entry.title}
                            </a>
                          </Typography.Text>
                        }
                        description={relative(entry.created_at)}
                      />
                    </List.Item>
                  )}
                />
              </div>
            ))
          )}
          {centre.hasNextPage && (
            <Button
              block
              loading={centre.isFetchingNextPage}
              onClick={() => void centre.fetchNextPage()}
              data-testid="notifications-more"
            >
              {t('notifications.more')}
            </Button>
          )}
        </Space>
      </Drawer>
    </>
  );
}
