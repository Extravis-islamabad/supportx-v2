import {
  ApiError,
  useIncidentCatalogue,
  useUpdateIncident,
  type Incident,
} from '@supportx/api-client';
import {
  FormProblem,
  lengthLimit,
  markHandled,
  useAppearance,
  useFormProblem,
  useLabel,
} from '@supportx/ui';
import { App, Input, Modal, Typography } from 'antd';
import { useState } from 'react';

import { scaleLabel } from '../labels';

/**
 * A card dropped on a priority column (WP-046b S3b): the record page's own priority change,
 * asked as a dialog. The same fields (the reason, and the edit reason when the tenant asks for
 * one) and the same save, so the server's rules apply exactly as they do on the record.
 */
export function PriorityMoveDialog({
  item,
  priority,
  onClose,
}: {
  item: Incident;
  priority: string | null;
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const catalogue = useIncidentCatalogue();
  const update = useUpdateIncident(item.id);
  const problem = useFormProblem();
  const [reason, setReason] = useState('');
  const [why, setWhy] = useState('');
  const [error, setError] = useState<string | null>(null);
  const needsWhy =
    item.operations.find((o) => o.action === 'edit')?.reason_mode === 'required' ||
    (catalogue.data?.closure.edit_reason_fields ?? []).includes('priority');
  const name = priority === null ? '' : scaleLabel(t, catalogue.data, 'priority', priority, locale);
  const save = () => {
    problem.clear();
    const changes: Record<string, unknown> = { priority, priority_reason: reason };
    if (needsWhy) changes.edit_reason = why;
    update.mutate(
      { changes, version: item.version },
      {
        onSuccess: () => {
          void message.success(t('incidents.saved'));
          onClose();
        },
        onError: (failure) => {
          if (failure instanceof ApiError && failure.fieldErrors.length > 0) {
            markHandled(failure);
            setError(failure.fieldErrors.map((e) => t(e.message_key, e.params)).join(' '));
            return;
          }
          // A version conflict or a rule's refusal: said here, and the card stays.
          problem.show(failure);
        },
      },
    );
  };
  return (
    <Modal
      open
      title={t('incidents.board.priority_title', { id: item.display_id, priority: name })}
      onCancel={onClose}
      onOk={save}
      okText={t('incidents.board.priority_ok')}
      okButtonProps={{ loading: update.isPending, 'data-testid': 'inc-board-priority-ok' }}
      destroyOnHidden
    >
      <Input
        aria-label={t('work_item.field.priority_reason')}
        placeholder={t('work_item.field.priority_reason')}
        value={reason}
        count={lengthLimit(500)}
        onChange={(event) => {
          setReason(event.target.value);
        }}
        data-testid="inc-board-priority-reason"
      />
      {needsWhy && (
        <Input.TextArea
          aria-label={t('incidents.edit_reason')}
          placeholder={t('incidents.edit_reason')}
          value={why}
          onChange={(event) => {
            setWhy(event.target.value);
          }}
          style={{ marginTop: 8 }}
          data-testid="inc-board-priority-why"
        />
      )}
      {error !== null && (
        <Typography.Text type="danger" role="alert">
          {error}
        </Typography.Text>
      )}
      <FormProblem problem={problem} />
    </Modal>
  );
}
