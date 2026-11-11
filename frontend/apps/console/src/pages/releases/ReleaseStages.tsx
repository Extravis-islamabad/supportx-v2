import { Flex, List, Segmented, Typography } from 'antd';
import { useState } from 'react';

import { useIncidentTasks, useIncidentWorklogs, useStagePanel } from '@supportx/api-client';
import { EmptyText, ToneTag, useLabel } from '@supportx/ui';

import { stageName } from './labels';

/**
 * A release's work by stage (WP-058b S3; REQ-REL-048, template A): pick a stage (the current one
 * first) to see its tasks, done of all, and the time logged in it. The full Tasks and Worklogs
 * tabs add and change them; this view reads. Live with the record (the page's channel).
 */
export function ReleaseStagesPart({ id }: { id: string }) {
  const t = useLabel();
  // Minutes in words, with the worklogs' own labels.
  const duration = (minutes: number) =>
    minutes >= 60
      ? t('incidents.worklogs.hours_minutes', {
          hours: Math.floor(minutes / 60),
          minutes: minutes % 60,
        })
      : t('incidents.worklogs.minutes', { minutes });
  const panel = useStagePanel(id);
  const tasks = useIncidentTasks(id, true, 'releases');
  const worklogs = useIncidentWorklogs(id, true, 'releases');
  const rail = panel.data?.rail ?? [];
  const [picked, setPicked] = useState<string>();
  const stage = picked ?? panel.data?.stage ?? rail[0]?.stage ?? '';
  const here = rail.find((s) => s.stage === stage);
  const own = (tasks.data?.items ?? []).filter((task) => task.stage === stage);
  const logged = (worklogs.data?.items ?? []).filter((w) => w.stage === stage);
  if (rail.length === 0) return null;
  return (
    <Flex vertical gap={16} data-testid="release-stage-work">
      <Segmented<string>
        value={stage}
        onChange={setPicked}
        options={rail.map((s) => ({ value: s.stage, label: stageName(t, s.stage) }))}
        data-testid="release-stage-pick"
        style={{ maxWidth: '100%', overflowX: 'auto' }}
      />
      <section aria-labelledby="release-stage-tasks">
        <Typography.Title level={5} id="release-stage-tasks">
          {t('stage_rail.tasks', { done: here?.tasks_done ?? 0, count: here?.tasks_total ?? 0 })}
        </Typography.Title>
        <List
          size="small"
          dataSource={own}
          locale={{ emptyText: <EmptyText>{t('releases.stages.no_tasks')}</EmptyText> }}
          renderItem={(task) => (
            <List.Item key={task.id} data-testid={`release-stage-task-${task.id}`}>
              <bdi dir="auto">{task.title}</bdi>
              <ToneTag tone={task.status === 'done' ? 'success' : 'default'}>
                {t(`task_status.${task.status}`)}
              </ToneTag>
            </List.Item>
          )}
        />
      </section>
      <section aria-labelledby="release-stage-time">
        <Typography.Title level={5} id="release-stage-time">
          {t('releases.stages.time', {
            time: duration(logged.reduce((sum, w) => sum + w.minutes, 0)),
          })}
        </Typography.Title>
        <List
          size="small"
          dataSource={logged}
          locale={{ emptyText: <EmptyText>{t('releases.stages.no_time')}</EmptyText> }}
          renderItem={(w) => (
            <List.Item key={w.id} data-testid={`release-stage-worklog-${w.id}`}>
              <span>{t(`worklog_type.${w.worklog_type}`)}</span>
              <span>{duration(w.minutes)}</span>
            </List.Item>
          )}
        />
      </section>
    </Flex>
  );
}
