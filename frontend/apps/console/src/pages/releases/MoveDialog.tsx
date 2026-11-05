import { Form, Input, Modal, Select } from 'antd';
import { useState } from 'react';

import { useMoveRelease, useReleaseSettings, type StageMove } from '@supportx/api-client';
import {
  DateTimeField,
  FormProblem,
  lengthLimit,
  useAppearance,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

import { labelled } from '../incidents/labels';
import { statusName } from './labels';

const isDate = (field: string) => /_(start|end)$/.test(field);

/**
 * One move's dialog (REQ-REL-016, -018): the reason when the move asks for one, and only the
 * fields it still needs (`missing`), saved in the same request. A move into the closed status
 * asks for the closure code, as the closing rules do (lane A's review of ADR-041).
 */
export function MoveDialog({
  releaseId,
  version,
  move,
  onClose,
}: {
  releaseId: string;
  version: number;
  move: StageMove;
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const settings = useReleaseSettings();
  const moving = useMoveRelease();
  const problem = useFormProblem();
  const [reason, setReason] = useState('');
  const [fields, setFields] = useState<Record<string, string | null>>({});
  const [closureCode, setClosureCode] = useState<string>();
  const closing = move.to_status === 'closure_closed';
  const missing = move.missing ?? [];
  const needsReason = move.reason_mode === 'required';
  const ready =
    (!needsReason || reason.trim() !== '') &&
    missing.every((m) => (fields[m.field] ?? '') !== '') &&
    (!closing || closureCode !== undefined);
  const submit = () => {
    moving.mutate(
      {
        id: releaseId,
        version,
        body: {
          to_status: move.to_status,
          reason_text: reason.trim() === '' ? null : reason.trim(),
          fields: missing.length > 0 ? fields : null,
          confirm_open_work: false,
          closure_code: closing ? (closureCode ?? null) : null,
        },
      },
      {
        onSuccess: onClose,
        onError: (error) => {
          problem.show(error);
        },
      },
    );
  };
  return (
    <Modal
      open
      title={t('releases.move.title', { status: statusName(t, move.to_status) })}
      okText={t('releases.move.confirm')}
      okButtonProps={{ disabled: !ready, loading: moving.isPending, 'data-testid': 'move-ok' }}
      onOk={submit}
      onCancel={onClose}
      destroyOnHidden
    >
      <Form layout="vertical" data-testid="move-dialog">
        {missing.map((m) => (
          <Form.Item
            key={m.field}
            label={t(`work_item.field.${m.field.replace(/^custom\./, '')}`)}
            help={t(`errors.field.${m.code}`)}
            required
          >
            {isDate(m.field) ? (
              <DateTimeField
                value={fields[m.field] ?? null}
                onChange={(value) => {
                  setFields((now) => ({ ...now, [m.field]: value }));
                }}
                testId={`move-field-${m.field}`}
              />
            ) : (
              <Input
                value={fields[m.field] ?? ''}
                onChange={(e) => {
                  setFields((now) => ({ ...now, [m.field]: e.target.value }));
                }}
                data-testid={`move-field-${m.field}`}
              />
            )}
          </Form.Item>
        ))}
        {closing && (
          <Form.Item label={t('work_item.field.closure_code')} required>
            <Select
              value={closureCode}
              onChange={setClosureCode}
              data-testid="move-closure-code"
              options={(settings.data?.closure_codes ?? [])
                .filter((c) => !c.disabled)
                .map((c) => ({
                  value: c.code,
                  label: labelled(c.labels, locale, () => t(`closure_code.${c.code}`)),
                }))}
            />
          </Form.Item>
        )}
        {move.reason_mode !== 'none' && (
          <Form.Item label={t('releases.move.reason')} required={needsReason}>
            <Input.TextArea
              rows={3}
              count={lengthLimit(500)}
              value={reason}
              onChange={(e) => {
                setReason(e.target.value);
              }}
              data-testid="move-reason"
            />
          </Form.Item>
        )}
        <FormProblem problem={problem} />
      </Form>
    </Modal>
  );
}
