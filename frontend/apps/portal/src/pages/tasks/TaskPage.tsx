import { useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Flex, Form, Skeleton, Typography } from 'antd';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';

import {
  ApiError,
  portalTaskKeys,
  usePortalTask,
  useUpdatePortalTask,
  type CatalogQuestion,
  type PortalTask,
} from '@supportx/api-client';
import { refreshQueries, usePersonalChannel } from '@supportx/realtime';
import {
  markHandled,
  QuestionField,
  reportError,
  textIn,
  useAppearance,
  useLabel,
  type QuestionValue,
} from '@supportx/ui';

import { FormCard } from '../FormCard';
import { FORM_COLUMN } from '../formColumn';
import { MY_TASKS_CHANGED } from './MyTasksPage';

type TaskField = NonNullable<PortalTask['fields']>[number];

/** A task's own field as the shared question input reads it (the same kinds, P2). */
function asQuestion(field: TaskField): CatalogQuestion {
  return {
    key: field.key,
    label: field.label,
    kind: field.kind as CatalogQuestion['kind'],
    required: field.required,
    options: field.options,
  } as CatalogQuestion;
}

function empty(value: QuestionValue | undefined): boolean {
  return value == null || value === '' || (Array.isArray(value) && value.length === 0);
}

/**
 * One of your tasks (WP-047a S5; REQ-SR-049, -050): its name, the request's reference and its
 * own fields, nothing else of the request. Start it, fill in its fields, complete it; a
 * required field left empty keeps it open (AC1). Closed or given to someone else, it is gone.
 */
export function TaskPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const id = useParams().id ?? '';
  const found = usePortalTask(id);
  const update = useUpdatePortalTask(id);
  const [values, setValues] = useState<Record<string, QuestionValue> | null>(null);
  const [problems, setProblems] = useState<Record<string, string>>({});
  usePersonalChannel(
    (event) => {
      if (event.type === MY_TASKS_CHANGED && event.ids.includes(id)) {
        refreshQueries(queryClient, portalTaskKeys.detail(id));
      }
    },
    { covers: [portalTaskKeys.detail(id)] },
  );
  // Not yours, closed or given to someone else (404); any other failure is reported (lane C).
  if (found.error instanceof ApiError && found.error.status === 404) {
    return (
      <Flex vertical gap={16} style={FORM_COLUMN}>
        <Alert type="info" showIcon message={t('portal.tasks.gone')} />
        <Link to="/tasks">{t('portal.tasks.back')}</Link>
      </Flex>
    );
  }
  if (found.error) {
    // Any other failure (a server error, the network): say so and offer to try again, never a
    // skeleton forever (lane C's #630 note), and report it.
    reportError(found.error);
    return (
      <Flex vertical gap={16} style={FORM_COLUMN}>
        <Alert
          type="warning"
          showIcon
          message={t('portal.tasks.load_failed')}
          action={
            <Button
              size="small"
              onClick={() => {
                void found.refetch();
              }}
              data-testid="portal-task-retry"
            >
              {t('portal.tasks.retry')}
            </Button>
          }
        />
        <Link to="/tasks">{t('portal.tasks.back')}</Link>
      </Flex>
    );
  }
  const task = found.data;
  if (task === undefined) return <Skeleton active />;
  const fields = task.fields ?? [];
  const shown: Record<string, QuestionValue> =
    values ?? (task.field_values as Record<string, QuestionValue>);
  const missing = fields.filter((f) => f.required && empty(shown[f.key]));
  const handover = task.kind === 'asset_handover';
  const send = (status?: 'in_progress' | 'done') => {
    setProblems({});
    update.mutate(
      {
        change: {
          ...(status === undefined ? {} : { status }),
          ...(fields.length > 0 ? { field_values: shown } : {}),
        },
        version: task.version,
      },
      {
        onSuccess: () => {
          setValues(null);
          if (status === 'done') void navigate('/tasks', { replace: true });
        },
        onError: (error) => {
          if (error instanceof ApiError && error.status === 422) {
            markHandled(error);
            setProblems(
              Object.fromEntries(
                error.fieldErrors.map((f) => [
                  f.field.replace(/^(body\.)?field_values\./, ''),
                  t(f.message_key, f.params ?? {}),
                ]),
              ),
            );
            return;
          }
          reportError(error);
        },
      },
    );
  };
  return (
    <Flex vertical gap={16} style={FORM_COLUMN}>
      <Typography.Title level={1} style={{ margin: 0 }}>
        {task.title}
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
        {t('portal.tasks.for_request', { ref: task.request_ref })}
      </Typography.Paragraph>
      {handover && <Alert type="info" showIcon message={t('portal.tasks.handover_by_desk')} />}
      <FormCard testId="portal-task">
        <Form layout="vertical" requiredMark>
          {fields.map((field) => (
            <Form.Item
              key={field.key}
              label={textIn(field.label, locale) || field.key}
              required={field.required}
              htmlFor={`sr-q-${field.key}`}
              validateStatus={problems[field.key] !== undefined ? 'error' : undefined}
              help={problems[field.key]}
            >
              <QuestionField
                question={asQuestion(field)}
                value={shown[field.key] ?? null}
                onChange={(value) => {
                  setValues({ ...shown, [field.key]: value });
                }}
                locale={locale}
              />
            </Form.Item>
          ))}
          <Flex gap={8} align="center" wrap>
            {task.status === 'open' && (
              <Button
                loading={update.isPending}
                onClick={() => {
                  send('in_progress');
                }}
                data-testid="portal-task-start"
              >
                {t('portal.tasks.start')}
              </Button>
            )}
            {fields.length > 0 && (
              <Button
                loading={update.isPending}
                disabled={values === null}
                onClick={() => {
                  send();
                }}
                data-testid="portal-task-save"
              >
                {t('actions.save')}
              </Button>
            )}
            <Button
              type="primary"
              loading={update.isPending}
              disabled={missing.length > 0 || handover}
              onClick={() => {
                send('done');
              }}
              data-testid="portal-task-done"
            >
              {t('portal.tasks.complete')}
            </Button>
            {missing.length > 0 && (
              <Typography.Text type="secondary">{t('portal.tasks.fill_required')}</Typography.Text>
            )}
          </Flex>
        </Form>
      </FormCard>
    </Flex>
  );
}
