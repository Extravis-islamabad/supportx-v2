import { Button, Flex, List, Typography } from 'antd';
import { useMemo } from 'react';

import { useAuditEntries } from '@supportx/api-client';
import { hasLabel } from '@supportx/labels';
import { EmptyText, useAccess, useDateTime, useLabel } from '@supportx/ui';

const AUDIT_VIEW = 'audit.view';

/**
 * The erasure's audit entries (approval, rejection, report review, redactions, passage views),
 * through the audit log's own API filtered by the erasure: reading it needs the audit right, and
 * reading it is itself audited.
 */
export function ErasureHistory({ erasureId }: { erasureId: string }) {
  const t = useLabel();
  const dates = useDateTime();
  const { can } = useAccess();
  const allowed = can(AUDIT_VIEW);
  const entries = useAuditEntries(
    { params: { object_type: 'person_erasure', object_id: erasureId } },
    allowed,
  );
  const rows = useMemo(() => entries.data?.pages.flatMap((p) => p.items) ?? [], [entries.data]);
  if (!allowed) {
    return (
      <Typography.Text type="secondary" data-testid="erasure-history-no-access">
        {t('people_erasure.history_no_access')}
      </Typography.Text>
    );
  }
  return (
    <Flex vertical gap={8} data-testid="erasure-history">
      <List
        loading={entries.isPending}
        dataSource={rows}
        locale={{ emptyText: <EmptyText>{t('people_erasure.history_none')}</EmptyText> }}
        renderItem={(entry) => {
          const action = `audit.action.${entry.action}`;
          return (
            <List.Item key={entry.id}>
              <Flex vertical>
                <span>{hasLabel(action) ? t(action) : t('people_erasure.history_other')}</span>
                <Typography.Text type="secondary">
                  <bdi dir="auto">{entry.actor_name ?? t('people_erasure.unknown_person')}</bdi>
                  {' · '}
                  <span title={dates.format(entry.occurred_at)}>
                    {dates.relative(entry.occurred_at)}
                  </span>
                </Typography.Text>
              </Flex>
            </List.Item>
          );
        }}
      />
      {entries.hasNextPage && (
        <Button onClick={() => void entries.fetchNextPage()} loading={entries.isFetchingNextPage}>
          {t('people_erasure.load_more')}
        </Button>
      )}
    </Flex>
  );
}
