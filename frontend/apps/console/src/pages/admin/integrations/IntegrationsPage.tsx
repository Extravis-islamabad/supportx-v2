import { useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Card, Empty, Flex, Input, Space, Tooltip, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';

import {
  queryKeys,
  useConnectorCatalogue,
  type ConnectorInstance,
  type ConnectorKind,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import { ToneTag, useDateTime, useLabel, type Tone } from '@supportx/ui';

const STATUS_TONE: Record<ConnectorInstance['status'], Tone> = {
  not_set_up: 'default',
  active: 'success',
  degraded: 'warning',
  failed: 'error',
  paused: 'info',
};

/** What the search box matches: the labelled name, category, description and keywords. */
function searchable(kind: ConnectorKind, t: (key: string) => string): string {
  return [
    t(`connector_kind.${kind.code}`),
    t(`connector_kind.${kind.code}.description`),
    t(`connector_category.${kind.category}`),
    ...kind.keywords.map((keyword) => t(keyword)),
    ...kind.instances.map((instance) => instance.name),
  ]
    .join(' ')
    .toLocaleLowerCase();
}

function InstanceRow({ kind, instance }: { kind: ConnectorKind; instance: ConnectorInstance }) {
  const t = useLabel();
  const dates = useDateTime();
  const counts = instance.counts_24h;
  const reason = instance.reason ?? instance.last_error_code;
  return (
    <Flex vertical gap={4} data-testid={`connector-instance-${instance.id}`}>
      <Space wrap size={8}>
        <Typography.Text strong>
          {/* A user-given name (an address): isolated so it never reorders a sentence (RTL). */}
          <bdi>{instance.name}</bdi>
        </Typography.Text>
        <ToneTag tone={STATUS_TONE[instance.status]} testId="connector-status">
          {t(`connector_status.${instance.status}`)}
        </ToneTag>
      </Space>
      {reason != null && instance.status !== 'active' && (
        <Typography.Text type="secondary">{t(`${kind.reason_labels}.${reason}`)}</Typography.Text>
      )}
      <Typography.Text type="secondary">
        {instance.last_success_at != null
          ? t('integrations.last_success', { when: dates.format(instance.last_success_at) })
          : t('integrations.never_succeeded')}
        {' · '}
        {t('integrations.counts_24h', {
          runs: counts.runs ?? 0,
          read: counts.read ?? 0,
          failed: counts.failed_runs ?? 0,
        })}
      </Typography.Text>
      {instance.credential_expires_at != null && (
        <Typography.Text type="secondary">
          {t('integrations.credential_expires', {
            when: dates.format(instance.credential_expires_at),
          })}
        </Typography.Text>
      )}
    </Flex>
  );
}

function KindCard({ kind }: { kind: ConnectorKind }) {
  const t = useLabel();
  const whyReadOnly =
    kind.manage_reason != null ? t(`connector_manage_reason.${kind.manage_reason}`) : null;
  const navigate = useNavigate();
  const setUp = (
    <Button
      type="primary"
      disabled={!kind.can_manage}
      onClick={() => {
        void navigate(kind.page);
      }}
      data-testid="connector-set-up"
    >
      {t('integrations.set_up')}
    </Button>
  );
  return (
    <Card
      size="small"
      title={t(`connector_kind.${kind.code}`)}
      extra={
        whyReadOnly === null ? (
          setUp
        ) : (
          // A disabled button sends no pointer events: the wrapper carries the reason.
          <Tooltip title={whyReadOnly}>
            <span>{setUp}</span>
          </Tooltip>
        )
      }
      data-testid={`connector-kind-${kind.code}`}
    >
      <Flex vertical gap={12}>
        <Typography.Text type="secondary">
          {t(`connector_kind.${kind.code}.description`)}
        </Typography.Text>
        {whyReadOnly !== null && (
          <Typography.Text type="secondary" data-testid="connector-read-only">
            {whyReadOnly}
          </Typography.Text>
        )}
        {kind.instances.length === 0 ? (
          <Typography.Text type="secondary">{t('integrations.none_set_up')}</Typography.Text>
        ) : (
          kind.instances.map((instance) => (
            <InstanceRow key={instance.id} kind={kind} instance={instance} />
          ))
        )}
      </Flex>
    </Card>
  );
}

/**
 * Admin › Integrations (WP-040; REQ-INT-001, REQ-INT-004, REQ-INT-013): every connector by
 * category with its live status, searchable by name and by keywords such as "key". People
 * without set-up rights see it read-only, with the reason on each entry. A mailbox that starts
 * failing shows here within a minute, without a reload (`integrations.connectors_changed`).
 */
export function IntegrationsPage() {
  const t = useLabel();
  const queryClient = useQueryClient();
  const catalogue = useConnectorCatalogue();
  const [query, setQuery] = useState('');
  useTenantChannel((event) => {
    if (
      event.type === 'integrations.connectors_changed' ||
      event.type === 'integrations.mailboxes_changed'
    ) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.connectors.catalogue });
    }
  });
  const groups = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    const found = (catalogue.data ?? []).filter(
      (kind) => needle === '' || searchable(kind, t).includes(needle),
    );
    const byCategory = new Map<string, ConnectorKind[]>();
    for (const kind of found) {
      byCategory.set(kind.category, [...(byCategory.get(kind.category) ?? []), kind]);
    }
    return [...byCategory.entries()];
  }, [catalogue.data, query, t]);

  return (
    <Flex vertical gap={16} data-testid="admin-integrations">
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0, maxWidth: 720 }}>
        {t('integrations.intro')}
      </Typography.Paragraph>
      <Input.Search
        allowClear
        placeholder={t('integrations.search')}
        aria-label={t('integrations.search')}
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
        style={{ maxWidth: 420 }}
        data-testid="integrations-search"
      />
      {catalogue.isError && <Alert type="error" showIcon message={t('integrations.load_failed')} />}
      {catalogue.isSuccess && groups.length === 0 && (
        <Empty description={t('integrations.no_match')} />
      )}
      {groups.map(([category, kinds]) => (
        <Flex key={category} vertical gap={8} data-testid={`connector-category-${category}`}>
          <Typography.Title level={5} style={{ marginBottom: 0 }}>
            {t(`connector_category.${category}`)}
          </Typography.Title>
          {kinds.map((kind) => (
            <KindCard key={kind.code} kind={kind} />
          ))}
        </Flex>
      ))}
    </Flex>
  );
}
