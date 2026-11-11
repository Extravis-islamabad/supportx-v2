import { Alert, Form, Input, Modal } from 'antd';
import { useState } from 'react';

import { useEmergencyOverride } from '@supportx/api-client';
import { FormProblem, lengthLimit, useFormProblem, useLabel } from '@supportx/ui';

/**
 * The emergency override (D-144): a change sent back for approval keeps going from where it
 * was. It needs the permission and a reason, is audited (refused attempts too), withdraws the
 * re-approval and makes the post-implementation review mandatory; the dialog says all of that
 * before the person confirms. The server decides; the record's If-Match goes with it.
 */
export function EmergencyOverrideDialog({
  id,
  version,
  onClose,
}: {
  id: string;
  version: number;
  onClose: () => void;
}) {
  const t = useLabel();
  const override = useEmergencyOverride();
  const problem = useFormProblem();
  const [reason, setReason] = useState('');
  return (
    <Modal
      open
      title={t('changes.override.title')}
      okText={t('changes.override.confirm')}
      okButtonProps={{
        danger: true,
        disabled: reason.trim() === '',
        loading: override.isPending,
        'data-testid': 'override-ok',
      }}
      onOk={() => {
        override.mutate(
          { id, version, reason: reason.trim() },
          {
            onSuccess: onClose,
            onError: (error) => {
              problem.show(error);
            },
          },
        );
      }}
      onCancel={onClose}
      destroyOnHidden
    >
      <Form layout="vertical" data-testid="override-dialog">
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('changes.override.warning')}
        />
        <Form.Item label={t('changes.override.reason')} required htmlFor="override-reason">
          <Input.TextArea
            id="override-reason"
            rows={3}
            count={lengthLimit(500)}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
            }}
            data-testid="override-reason"
          />
        </Form.Item>
        <FormProblem problem={problem} />
      </Form>
    </Modal>
  );
}
