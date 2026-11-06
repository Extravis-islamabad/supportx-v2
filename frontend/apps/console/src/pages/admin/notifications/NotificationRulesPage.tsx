import { useQueryClient } from '@tanstack/react-query';
import {
  App as AntApp,
  Button,
  Checkbox,
  Collapse,
  Flex,
  Input,
  Select,
  Skeleton,
  Switch,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from 'antd';
import { useMemo, useState } from 'react';

import {
  queryKeys,
  useNotificationRules,
  useResetNotificationRule,
  useSaveNotificationRule,
  type NotificationChannel,
  type NotificationRule,
  type NotificationRuleInput,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import { EmptyText, reportError, useDateTime, useLabel } from '@supportx/ui';

import { NotificationsBanner } from '../../../notifications/NotificationsBanner';

const CHANNELS: NotificationChannel[] = ['in_app', 'email'];
const PRIORITIES = ['p1', 'p2', 'p3', 'p4'];

function input(rule: NotificationRule): NotificationRuleInput {
  return {
    enabled: rule.enabled,
    recipients: rule.recipients,
    channels: rule.channels,
    user_ids: rule.user_ids,
    group_ids: rule.group_ids,
    conditions: rule.conditions,
    notify_actor: rule.notify_actor,
  };
}

/**
 * Admin › Notifications (WP-023, REQ-NTF-008): every event every module registered, with the
 * rule that applies, ready with no set-up step. Each row saves on its own with its version (a
 * second admin's change is a conflict, never overwritten), shows whether it still has the
 * shipped default, and can go back to it. Another admin's change shows here without a reload.
 */
export function NotificationRulesPage() {
  const t = useLabel();
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  const rules = useNotificationRules();
  const [search, setSearch] = useState('');
  const save = useSaveNotificationRule();
  const reset = useResetNotificationRule();
  const { format } = useDateTime();
  useTenantChannel((event) => {
    if (event.type === 'notifications.rules_changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.rules });
    }
  });

  const change = (rule: NotificationRule, changes: Partial<NotificationRuleInput>) => {
    save.mutate(
      { eventCode: rule.event_code, rule: { ...input(rule), ...changes }, version: rule.version },
      {
        onSuccess: () => void message.success(t('notification_rules.saved')),
        onError: reportError,
      },
    );
  };

  const priorityOnly = (rule: NotificationRule) =>
    rule.conditions.find((c) => c.field === 'priority' && c.operator === 'in')?.values ?? [];

  // Grouped by area (the record type), searched by the event's name (QA6S-CHN-01).
  const query = search.trim().toLocaleLowerCase();
  const areas = useMemo(() => {
    const found = new Map<string, NotificationRule[]>();
    for (const rule of rules.data ?? []) {
      const name = t(`notification_event.${rule.event_code}`).toLocaleLowerCase();
      if (query !== '' && !name.includes(query)) continue;
      const list = found.get(rule.record_type) ?? [];
      list.push(rule);
      found.set(rule.record_type, list);
    }
    return [...found.entries()];
  }, [rules.data, query, t]);
  const columns: TableColumnsType<NotificationRule> = [
    {
      key: 'event',
      title: t('notification_rules.col.event'),
      render: (_, rule) => (
        <Flex vertical gap={4}>
          <Typography.Text strong>{t(`notification_event.${rule.event_code}`)}</Typography.Text>
          <Flex gap={4} wrap>
            {rule.required && <Tag>{t('notification_rules.required')}</Tag>}
            {/* Only a changed rule is marked: a tag on every row said nothing (CHN-01). */}
            {!rule.is_default && (
              <Tag color="blue">
                {t('notification_rules.changed', { when: format(rule.updated_at) })}
              </Tag>
            )}
          </Flex>
        </Flex>
      ),
    },
    {
      key: 'on',
      title: t('notification_rules.col.on'),
      render: (_, rule) => (
        <Switch
          checked={rule.enabled}
          aria-label={t('notification_rules.col.on')}
          onChange={(on) => {
            change(rule, { enabled: on });
          }}
          data-testid={`rule-on-${rule.event_code}`}
        />
      ),
    },
    {
      key: 'recipients',
      title: t('notification_rules.col.recipients'),
      render: (_, rule) => (
        <Select
          mode="multiple"
          style={{ minWidth: 220 }}
          value={rule.recipients}
          aria-label={t('notification_rules.col.recipients')}
          options={rule.recipient_kinds.map((kind) => ({
            value: kind,
            label: t(`notification_recipient.${kind}`),
          }))}
          onChange={(recipients) => {
            change(rule, { recipients });
          }}
          data-testid={`rule-recipients-${rule.event_code}`}
        />
      ),
    },
    {
      key: 'channels',
      title: t('notification_rules.col.channels'),
      render: (_, rule) => (
        <Checkbox.Group
          value={rule.channels}
          options={CHANNELS.map((c) => ({ value: c, label: t(`notification_channel.${c}`) }))}
          onChange={(channels) => {
            change(rule, { channels });
          }}
          data-testid={`rule-channels-${rule.event_code}`}
        />
      ),
    },
    {
      key: 'priority',
      title: t('notification_rules.col.priority'),
      render: (_, rule) =>
        rule.condition_fields.includes('priority') ? (
          <Select
            mode="multiple"
            allowClear
            style={{ minWidth: 160 }}
            placeholder={t('notification_rules.any_priority')}
            value={priorityOnly(rule)}
            aria-label={t('notification_rules.col.priority')}
            options={PRIORITIES.map((p) => ({ value: p, label: t(`priority.${p}`) }))}
            onChange={(values) => {
              const others = rule.conditions.filter((c) => c.field !== 'priority');
              change(rule, {
                conditions:
                  values.length === 0
                    ? others
                    : [...others, { field: 'priority', operator: 'in', values }],
              });
            }}
            data-testid={`rule-priority-${rule.event_code}`}
          />
        ) : null,
    },
    {
      key: 'reset',
      render: (_, rule) =>
        rule.is_default ? null : (
          <Button
            size="small"
            onClick={() => {
              reset.mutate(
                { eventCode: rule.event_code, version: rule.version },
                { onError: reportError },
              );
            }}
            data-testid={`rule-reset-${rule.event_code}`}
          >
            {t('notification_rules.reset')}
          </Button>
        ),
    },
  ];

  return (
    <Flex vertical gap={16} data-testid="admin-notifications">
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        {t('notification_rules.intro')}
      </Typography.Paragraph>
      <NotificationsBanner />
      <Input.Search
        allowClear
        aria-label={t('notification_rules.search')}
        placeholder={t('notification_rules.search')}
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
        }}
        style={{ maxWidth: 360 }}
        data-testid="notification-rules-search"
      />
      {rules.isPending ? (
        <Skeleton active />
      ) : areas.length === 0 ? (
        <EmptyText>{t('notification_rules.none')}</EmptyText>
      ) : (
        <Collapse
          defaultActiveKey={areas.map(([area]) => area)}
          {...(query === '' ? {} : { activeKey: areas.map(([area]) => area) })}
          data-testid="notification-rules"
          items={areas.map(([area, rows]) => ({
            key: area,
            label: `${t(`notification_area.${area}`)} (${String(rows.length)})`,
            children: (
              <Table<NotificationRule>
                rowKey="event_code"
                dataSource={rows}
                pagination={false}
                size="small"
                scroll={{ x: 'max-content' }}
                columns={columns}
                data-testid={`notification-rules-${area}`}
              />
            ),
          }))}
        />
      )}
    </Flex>
  );
}
