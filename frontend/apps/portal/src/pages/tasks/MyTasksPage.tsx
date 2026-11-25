import { useQueryClient } from '@tanstack/react-query';
import { Card, Flex, List, Typography } from 'antd';
import { Link } from 'react-router';

import { portalTaskKeys, usePortalTasks } from '@supportx/api-client';
import { usePersonalChannel } from '@supportx/realtime';
import { EmptyText, reportError, ToneTag, useDateTime, useLabel } from '@supportx/ui';

// Sent on the person's own channel when a task is given to them, changes or leaves them.
export const MY_TASKS_CHANGED = 'work_items.my_tasks_changed';

/**
 * Your tasks (WP-047a S5; REQ-SR-050): the open tasks a request's plan gave you, each on its
 * own. Nothing else of the request shows (the coordinator's condition 1), only its reference.
 * Live: a task given to you, changed, completed or given to someone else refetches the list.
 */
export function MyTasksPage() {
  const t = useLabel();
  const { format } = useDateTime();
  const queryClient = useQueryClient();
  const found = usePortalTasks();
  usePersonalChannel(
    (event) => {
      if (event.type === MY_TASKS_CHANGED) {
        void queryClient.invalidateQueries({ queryKey: portalTaskKeys.all });
      }
    },
    { covers: [portalTaskKeys.all] },
  );
  if (found.error) reportError(found.error);
  const rows = found.data?.items ?? [];
  return (
    <Flex vertical gap={16}>
      <Typography.Title level={1} style={{ margin: 0 }}>
        {t('portal.tasks.title')}
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
        {t('portal.tasks.intro')}
      </Typography.Paragraph>
      <Card>
        <List
          loading={found.isLoading}
          dataSource={rows}
          data-testid="portal-tasks"
          locale={{ emptyText: <EmptyText>{t('portal.tasks.none')}</EmptyText> }}
          renderItem={(task) => (
            <List.Item key={task.id} data-testid={`portal-task-${task.id}`}>
              <List.Item.Meta
                title={<Link to={`/tasks/${task.id}`}>{task.title}</Link>}
                description={
                  task.due_at == null
                    ? t('portal.tasks.for_request', { ref: task.request_ref })
                    : t('portal.tasks.for_request_due', {
                        ref: task.request_ref,
                        due: format(task.due_at),
                      })
                }
              />
              <ToneTag tone={task.status === 'in_progress' ? 'info' : 'default'}>
                {t(`task_status.${task.status}`)}
              </ToneTag>
            </List.Item>
          )}
        />
      </Card>
    </Flex>
  );
}
