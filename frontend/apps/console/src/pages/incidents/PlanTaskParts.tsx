import { Alert, Button, Flex, Form, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useTaskChange,
  type CatalogQuestion,
  type IncidentTask,
  type PartsBase,
} from '@supportx/api-client';
import {
  markHandled,
  QuestionField,
  reportError,
  textIn,
  useAppearance,
  useLabel,
  type QuestionValue,
} from '@supportx/ui';

import { AssetPicker } from '../assets/AssetRelations';
import { UserPicker } from './pickers';

type TaskField = NonNullable<IncidentTask['fields']>[number];

/** A task's own field as the shared question input reads it (the same kinds). */
function asQuestion(field: TaskField): CatalogQuestion {
  return {
    key: field.key,
    label: field.label,
    kind: field.kind as CatalogQuestion['kind'],
    required: field.required,
    options: field.options ?? [],
  } as CatalogQuestion;
}

/**
 * A plan task's own parts (WP-047a S5): the fields its owner fills in (REQ-SR-049; a required
 * one empty keeps it open), a hand-over's asset (REQ-SR-056: completing it gives the asset to the
 * requested-for person, as you may, and links it to the request), and the flag a person decides
 * when a changed answer no longer wants it but work was done on it (REQ-SR-048 AC2).
 */
export function PlanTaskParts({
  task,
  base,
  recordId,
  onDone,
}: {
  task: IncidentTask;
  base: PartsBase;
  recordId: string;
  onDone: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const change = useTaskChange(recordId, base);
  const fields = task.fields ?? [];
  const [values, setValues] = useState<Record<string, QuestionValue>>(
    () => (task.field_values ?? {}) as Record<string, QuestionValue>,
  );
  const [asset, setAsset] = useState<string | undefined>(undefined);
  const [problems, setProblems] = useState<Record<string, string>>({});
  const closed = task.status === 'done' || task.status === 'canceled';
  const send = (patch: Record<string, unknown>) => {
    setProblems({});
    change.mutate(
      { kind: 'update', taskId: task.id, version: task.version, task: patch },
      {
        onSuccess: onDone,
        onError: (error) => {
          if (error instanceof ApiError && error.status === 422) {
            markHandled(error);
            setProblems(
              Object.fromEntries(
                error.fieldErrors.map((f) => [
                  f.field.replace(/^(body\.)?(field_values\.)?/, ''),
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
    <Flex vertical gap={12} data-testid="plan-task-parts">
      {task.needs_review && <Alert type="warning" showIcon message={t('task.plan.needs_review')} />}
      {fields.length > 0 && (
        <Form layout="vertical" requiredMark>
          <Typography.Text strong>{t('task.plan.fields')}</Typography.Text>
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
                value={values[field.key] ?? null}
                disabled={closed}
                onChange={(value) => {
                  setValues({ ...values, [field.key]: value });
                }}
                locale={locale}
                renderPerson={({ id, value, onChange, disabled }) => (
                  <UserPicker
                    value={value}
                    onChange={onChange}
                    testId={id}
                    ariaLabel={textIn(field.label, locale) || field.key}
                    disabled={disabled}
                  />
                )}
              />
            </Form.Item>
          ))}
          {!closed && (
            <Button
              loading={change.isPending}
              onClick={() => {
                send({ field_values: values });
              }}
              data-testid="plan-task-save-fields"
            >
              {t('task.plan.save_fields')}
            </Button>
          )}
        </Form>
      )}
      {task.kind === 'asset_handover' && !closed && (
        <Flex vertical gap={8} data-testid="plan-task-handover">
          <Typography.Text strong>{t('task.plan.handover')}</Typography.Text>
          <Typography.Text type="secondary">{t('task.plan.handover_help')}</Typography.Text>
          <AssetPicker
            value={asset}
            onChange={setAsset}
            exclude=""
            testId="plan-task-asset"
            ariaLabel={t('task.plan.handover_asset')}
          />
          {problems.asset_id !== undefined && (
            <Typography.Text type="danger">{problems.asset_id}</Typography.Text>
          )}
          <Button
            type="primary"
            disabled={asset === undefined}
            loading={change.isPending}
            onClick={() => {
              send({
                status: 'done',
                asset_id: asset,
                ...(fields.length > 0 ? { field_values: values } : {}),
              });
            }}
            data-testid="plan-task-handover-done"
          >
            {t('task.plan.handover_done')}
          </Button>
        </Flex>
      )}
    </Flex>
  );
}
