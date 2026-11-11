import { Button, Flex, Progress, Typography } from 'antd';

import { useWorkflowJob } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

/** A queued job's progress, live: the queue channel says when it moved. */
export function JobProgress({ id, onDone }: { id: string; onDone: () => void }) {
  const t = useLabel();
  const job = useWorkflowJob(id);
  const data = job.data;
  if (data === undefined) return null;
  const finished = data.status === 'done' || data.status === 'failed';
  return (
    <Flex gap={12} align="center" wrap data-testid={`workflow-job-${id}`} style={{ minWidth: 0 }}>
      <Typography.Text>
        {t(`workflow_job_kind.${data.kind}`)} ·{' '}
        {t('workflows.runs.job_counts', {
          done: data.done_count,
          skipped: data.skipped_count,
          total: data.total,
        })}
      </Typography.Text>
      <Progress
        percent={data.total === 0 ? 100 : Math.round((data.processed / data.total) * 100)}
        status={data.status === 'failed' ? 'exception' : finished ? 'success' : 'active'}
        style={{ width: 160 }}
        aria-label={t(`workflow_job_status.${data.status}`)}
      />
      {finished && (
        <Button size="small" onClick={onDone}>
          {t('workflows.runs.job_dismiss')}
        </Button>
      )}
    </Flex>
  );
}
