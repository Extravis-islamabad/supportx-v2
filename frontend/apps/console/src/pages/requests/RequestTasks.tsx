import { Checkbox, List, Space, Typography } from 'antd';

import { useRequestTasks, useRequestTaskStatus } from '@supportx/api-client';
import { reportError, ToneTag, useLabel } from '@supportx/ui';

/**
 * A request's tasks (WP-030 s3, REQ-SR-046, -058): the fulfilment plan's in order, which are
 * required and which internal; ticking one done saves it with If-Match, and the last required
 * one done fulfils the request on the server. Live through the record channel (the page
 * invalidates the record's queries, these included).
 */
export function RequestTasks({ recordId, canEdit }: { recordId: string; canEdit: boolean }) {
  const t = useLabel();
  const found = useRequestTasks(recordId);
  const change = useRequestTaskStatus(recordId);
  const rows = found.data?.items ?? [];
  if (found.isLoading || rows.length === 0) return null;
  return (
    <List
      header={<Typography.Text strong>{t('requests.tasks')}</Typography.Text>}
      bordered
      dataSource={rows}
      data-testid="sr-tasks"
      renderItem={(task) => (
        <List.Item key={task.id} data-testid={`sr-task-${String(task.position)}`}>
          <Space wrap>
            <Checkbox
              checked={task.status === 'done'}
              disabled={!canEdit || change.isPending || task.status === 'canceled'}
              onChange={(e) => {
                change.mutate(
                  { task, status: e.target.checked ? 'done' : 'open' },
                  { onError: reportError },
                );
              }}
              aria-label={task.title}
            >
              <bdi>{task.title}</bdi>
            </Checkbox>
            {task.from_plan && !task.required && (
              <ToneTag tone="info">{t('requests.task_optional')}</ToneTag>
            )}
            {task.internal && <ToneTag tone="info">{t('requests.task_internal')}</ToneTag>}
          </Space>
        </List.Item>
      )}
    />
  );
}
