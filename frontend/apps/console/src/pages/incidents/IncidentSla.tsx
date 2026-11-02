import { App, Button, Descriptions, Input, Modal, Space, Tag, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useIncidentSla,
  useSetIncidentDueDate,
  type Incident,
  type IncidentSlaTarget,
  type SlaTargetKind,
} from '@supportx/api-client';
import {
  ConflictDialog,
  DateTimeField,
  FormProblem,
  lengthLimit,
  markHandled,
  useConflict,
  useDateTime,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { incidentView, useIncidentFieldName } from './conflict';

const REASON_MAX = 500;

/** Colour by state: overdue stands out, met is calm, the rest neutral. */
function stateColour(target: IncidentSlaTarget): string | undefined {
  if (target.state === 'breached') return 'error';
  if (target.state === 'met') return target.met_how === 'late' ? 'warning' : 'success';
  return undefined;
}

/**
 * The record's SLA (REQ-SLA-038): the policy and why it applies, then each target with its due
 * moment, state, calendar and a due date set by hand with who and why (REQ-SLA-028). Read-only
 * apart from "Change due date", offered only when the server says the reader may.
 * Live: its query sits under the record's history, which every save of the record refreshes.
 */
export function IncidentSla({ item }: { item: Incident }) {
  const t = useLabel();
  const dates = useDateTime();
  const sla = useIncidentSla(item.id);
  const [editing, setEditing] = useState<IncidentSlaTarget | null>(null);
  if (sla.data === undefined) return null;
  const panel = sla.data;
  if (panel.policy_id === null) {
    return (
      <Typography.Text type="secondary" data-testid="inc-sla-none">
        {t('incidents.no_sla')}
      </Typography.Text>
    );
  }
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }} data-testid="inc-sla">
      <Descriptions column={1} size="small">
        <Descriptions.Item label={t('incidents.sla.policy')}>
          <bdi data-testid="inc-sla-policy">{panel.policy_name ?? ''}</bdi>
        </Descriptions.Item>
        {panel.reason !== null && (
          <Descriptions.Item label={t('incidents.sla.applied')}>
            {t(`sla_applied_reason.${panel.reason}`)} · {dates.format(panel.applied_at)}
          </Descriptions.Item>
        )}
      </Descriptions>
      {panel.targets.map((target) => (
        <Descriptions
          key={target.kind}
          column={1}
          size="small"
          title={t(`sla_target_kind.${target.kind}`)}
          data-testid={`inc-sla-${target.kind}`}
          extra={
            <Tag color={stateColour(target)} data-testid={`inc-sla-${target.kind}-state`}>
              {target.state === 'met' && target.met_how !== null
                ? t(`sla_met_how.${target.met_how}`)
                : t(`sla_target_state.${target.state}`)}
            </Tag>
          }
        >
          {target.due_at !== null && (
            <Descriptions.Item label={t('incidents.sla.due')}>
              <span data-testid={`inc-sla-${target.kind}-due`}>{dates.format(target.due_at)}</span>
            </Descriptions.Item>
          )}
          {target.paused_since !== null && target.state === 'paused' && (
            <Descriptions.Item label={t('incidents.sla.paused_since')}>
              {dates.format(target.paused_since)}
            </Descriptions.Item>
          )}
          {target.met_at !== null && (
            <Descriptions.Item label={t('incidents.sla.met_at')}>
              {dates.format(target.met_at)}
            </Descriptions.Item>
          )}
          {target.breached_at !== null && (
            <Descriptions.Item label={t('incidents.sla.breached_at')}>
              {dates.format(target.breached_at)}
            </Descriptions.Item>
          )}
          {target.calendar_name !== null && (
            <Descriptions.Item label={t('incidents.sla.calendar')}>
              <bdi>{target.calendar_name}</bdi>
            </Descriptions.Item>
          )}
          {target.manual !== null && (
            <Descriptions.Item>
              <Space direction="vertical" size={0} data-testid={`inc-sla-${target.kind}-manual`}>
                <Typography.Text>
                  {t('incidents.sla.set_by_hand', {
                    name: target.manual.by_name ?? '',
                    reason: target.manual.reason ?? '',
                  })}
                </Typography.Text>
                <Typography.Text type="secondary">{t('incidents.sla.manual_note')}</Typography.Text>
              </Space>
            </Descriptions.Item>
          )}
          {panel.may_set_due_dates && ['running', 'paused', 'breached'].includes(target.state) && (
            <Descriptions.Item>
              <Button
                size="small"
                onClick={() => {
                  setEditing(target);
                }}
                data-testid={`inc-sla-${target.kind}-change`}
              >
                {t('incidents.sla.change_due')}
              </Button>
            </Descriptions.Item>
          )}
        </Descriptions>
      ))}
      {editing !== null && (
        <DueDateDialog
          item={item}
          target={editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      )}
    </Space>
  );
}

/** Set a due date by hand, or go back to the SLA's own date; both need a reason. */
function DueDateDialog({
  item,
  target,
  onClose,
}: {
  item: Incident;
  target: IncidentSlaTarget;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const save = useSetIncidentDueDate(item.id);
  const problem = useFormProblem();
  const conflict = useConflict();
  const fieldName = useIncidentFieldName();
  const [dueAt, setDueAt] = useState<string | null>(target.manual?.due_at ?? target.due_at);
  const [reason, setReason] = useState('');
  const [opened] = useState(item);
  const kind: SlaTargetKind = target.kind;
  const run = (clear: boolean, version = item.version) => {
    problem.clear();
    save.mutate(
      { version, kind, dueAt: clear ? null : dueAt, reason },
      {
        onSuccess: () => {
          void message.success(t(clear ? 'incidents.sla.due_cleared' : 'incidents.sla.due_saved'));
          onClose();
        },
        onError: (error) => {
          if (conflict.take(error)) return;
          if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
            markHandled(error); // shown in the dialog
            return;
          }
          problem.show(error);
        },
      },
    );
  };
  const errors =
    save.error instanceof ApiError ? save.error.fieldErrors.map((e) => t(e.message_key)) : [];
  const blank = reason.trim() === '';
  return (
    <>
      <Modal
        open
        title={t('incidents.sla.due_dialog_title', { target: t(`sla_target_kind.${kind}`) })}
        onCancel={onClose}
        destroyOnHidden
        footer={[
          <Button key="cancel" onClick={onClose}>
            {t('actions.cancel')}
          </Button>,
          target.manual !== null && (
            <WriteButton
              key="clear"
              disabled={blank}
              loading={save.isPending}
              onClick={() => {
                run(true);
              }}
              data-testid="inc-sla-due-clear"
            >
              {t('incidents.sla.clear_due')}
            </WriteButton>
          ),
          <WriteButton
            key="save"
            type="primary"
            disabled={blank || dueAt === null}
            loading={save.isPending}
            onClick={() => {
              run(false);
            }}
            data-testid="inc-sla-due-save"
          >
            {t('actions.save')}
          </WriteButton>,
        ]}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <FormProblem problem={problem} />
          <label>
            <Typography.Text>{t('incidents.sla.new_due')}</Typography.Text>
            <DateTimeField value={dueAt} onChange={setDueAt} testId="inc-sla-due-at" />
          </label>
          <label>
            <Typography.Text>{t('incidents.sla.reason')}</Typography.Text>
            <Input.TextArea
              value={reason}
              onChange={(event) => {
                setReason(event.target.value);
              }}
              count={lengthLimit(REASON_MAX)}
              autoSize={{ minRows: 2 }}
              data-testid="inc-sla-due-reason"
            />
          </label>
          {errors.length > 0 && (
            <Typography.Text type="danger" role="alert">
              {errors.join(' ')}
            </Typography.Text>
          )}
        </Space>
      </Modal>
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={fieldName}
        opened={incidentView(opened)}
        latest={incidentView(item)}
        onReload={() => {
          conflict.clear();
          save.reset();
          onClose();
        }}
        onKeepMine={() => {
          conflict.clear();
          run(dueAt === null, conflict.latestVersion ?? item.version);
        }}
      />
    </>
  );
}
