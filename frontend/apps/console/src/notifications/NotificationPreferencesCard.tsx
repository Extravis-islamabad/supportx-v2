import { App as AntApp, Card, Checkbox, Switch, Table, Tooltip, Typography } from 'antd';

import {
  useNotificationPreferences,
  useSaveNotificationPreferences,
  type NotificationCategory,
  type NotificationChannel,
  type NotificationChoice,
} from '@supportx/api-client';
import { reportError, useLabel } from '@supportx/ui';

const CHANNELS: NotificationChannel[] = ['in_app', 'email'];

/**
 * My profile › Notifications (WP-023, REQ-NTF-016): which kinds of notification you get on which
 * channel, and do-not-disturb. Events your organization requires (assignments, mentions) are
 * shown on and locked, with the reason. Saved for you, so every device follows at once.
 */
export function NotificationPreferencesCard() {
  const t = useLabel();
  const { message } = AntApp.useApp();
  const preferences = useNotificationPreferences();
  const save = useSaveNotificationPreferences();
  const data = preferences.data;
  const categories = [...new Set(data?.choices.map((c) => c.category) ?? [])];
  const choice = (category: NotificationCategory, channel: NotificationChannel) =>
    data?.choices.find((c) => c.category === category && c.channel === channel);

  const store = (choices: NotificationChoice[], doNotDisturb: boolean) => {
    if (data === undefined) return;
    save.mutate(
      {
        off: choices
          .filter((c) => !c.on && !c.locked)
          .map((c) => ({ category: c.category, channel: c.channel })),
        doNotDisturb,
        version: data.version,
      },
      {
        onSuccess: () => void message.success(t('notification_preferences.saved')),
        onError: reportError,
      },
    );
  };

  return (
    <Card
      title={t('notification_preferences.title')}
      loading={preferences.isPending}
      data-testid="notification-preferences"
    >
      <Typography.Paragraph type="secondary">
        {t('notification_preferences.help')}
      </Typography.Paragraph>
      <Table
        size="small"
        pagination={false}
        rowKey={(category) => category}
        dataSource={categories}
        columns={[
          {
            key: 'category',
            title: t('notification_preferences.col.category'),
            render: (_, category) => t(`notification_category.${category}`),
          },
          ...CHANNELS.map((channel) => ({
            key: channel,
            title: t(`notification_channel.${channel}`),
            render: (_: unknown, category: NotificationCategory) => {
              const current = choice(category, channel);
              if (current === undefined) return null;
              const box = (
                <Checkbox
                  checked={current.on}
                  disabled={current.locked || save.isPending}
                  aria-label={`${t(`notification_category.${category}`)}: ${t(`notification_channel.${channel}`)}`}
                  onChange={(event) => {
                    store(
                      (data?.choices ?? []).map((c) =>
                        c === current ? { ...c, on: event.target.checked } : c,
                      ),
                      data?.do_not_disturb ?? false,
                    );
                  }}
                  data-testid={`pref-${category}-${channel}`}
                />
              );
              return current.locked ? (
                <Tooltip title={t('notification_preferences.locked')}>{box}</Tooltip>
              ) : (
                box
              );
            },
          })),
        ]}
      />
      <Typography.Paragraph style={{ marginTop: 16, marginBottom: 0 }}>
        <Switch
          checked={data?.do_not_disturb ?? false}
          disabled={data === undefined}
          loading={save.isPending}
          aria-label={t('notifications.do_not_disturb')}
          onChange={(on) => {
            store(data?.choices ?? [], on);
          }}
          data-testid="pref-dnd"
        />{' '}
        {t('notifications.do_not_disturb')}
        <Typography.Text type="secondary">
          {' '}
          {t('notification_preferences.dnd_help')}
        </Typography.Text>
      </Typography.Paragraph>
    </Card>
  );
}
