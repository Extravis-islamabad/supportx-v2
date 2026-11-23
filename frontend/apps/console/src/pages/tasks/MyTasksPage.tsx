import { useQueryClient } from '@tanstack/react-query';
import { Card, Flex, List, Tag, Typography } from 'antd';
import { Link } from 'react-router';

import { useAllMyTasks } from '@supportx/api-client';
import { usePersonalChannel } from '@supportx/realtime';
import { EmptyText, reportError, ToneTag, useDateTime, useLabel } from '@supportx/ui';

// The console path of each work item type's record.
const RECORD_PATH: Record<string, string> = {
  incident: 'incidents',
  service_request: 'requests',
  problem: 'problems',
  change: 'changes',
  release: 'releases',
};

/**
 * My tasks (WP-046a S1; REQ-INC-076): the open tasks you own on every work item type, due first,
 * overdue marked (AC2). Only records you may still see are listed. Live: assigning a task to you
 * reaches your own channel and the list refetches (AC1).
 */
export function MyTasksPage() {
  const t = useLabel();
  const { format } = useDateTime();
  const queryClient = useQueryClient();
  const found = useAllMyTasks();
  usePersonalChannel((event) => {
    if (event.type === 'work_items.my_tasks_changed' || event.type === 'work_items.changed') {
      void queryClient.invalidateQueries({ queryKey: ['my-tasks'] });
    }
  });
  if (found.error) reportError(found.error);
  const rows = found.data ?? [];
  return (
    <Flex vertical gap={16}>
      <Typography.Title level={1} style={{ margin: 0 }}>
        {t('my_tasks.title')}
      </Typography.Title>
      <Card>
        <List
          loading={found.isLoading}
          dataSource={rows}
          data-testid="my-tasks"
          locale={{ emptyText: <EmptyText>{t('my_tasks.none')}</EmptyText> }}
          renderItem={(row) => (
            <List.Item key={row.task.id} data-testid={`my-task-${row.task.id}`}>
              <Flex vertical gap={4} style={{ minWidth: 0 }}>
                <Flex gap={8} wrap align="center">
                  <bdi>{row.task.title}</bdi>
                  <Tag>{t(`task_status.${row.task.status}`)}</Tag>
                  {row.task.overdue && (
                    <ToneTag tone="error" testId={`my-task-overdue-${row.task.id}`}>
                      {t('incidents.tasks.overdue')}
                    </ToneTag>
                  )}
                  {(row.task.blocked_by ?? []).length > 0 && (
                    <ToneTag tone="warning">{t('my_tasks.blocked')}</ToneTag>
                  )}
                </Flex>
                <Typography.Text type="secondary">
                  <Link to={`/${RECORD_PATH[row.record_type] ?? 'incidents'}/${row.work_item_id}`}>
                    <span dir="ltr">{row.display_id}</span> · <bdi>{row.subject}</bdi>
                  </Link>
                  {row.task.due_at != null && (
                    <> · {t('incidents.tasks.due', { at: format(row.task.due_at) })}</>
                  )}
                </Typography.Text>
              </Flex>
            </List.Item>
          )}
        />
      </Card>
    </Flex>
  );
}
