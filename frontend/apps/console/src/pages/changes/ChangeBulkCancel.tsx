import { Form, Input, Modal, Typography } from 'antd';
import { useState } from 'react';

import { useStartChangeBulk } from '@supportx/api-client';
import { FormProblem, lengthLimit, useFormProblem, useLabel } from '@supportx/ui';

/**
 * Cancel the picked changes, or move them to the trash (REQ-CHG-101; WP-046a S1 PR 2). A cancel
 * needs one reason for all; each change still cancels by its own move, so one past the point a
 * cancel is offered is skipped and the progress drawer says why.
 */
export function ChangeBulkCancel({
  ids,
  action,
  onClose,
  onStarted,
}: {
  ids: string[];
  action: 'cancel' | 'delete' | null;
  onClose: () => void;
  onStarted: (jobId: string) => void;
}) {
  const t = useLabel();
  const start = useStartChangeBulk();
  const problem = useFormProblem();
  const [reason, setReason] = useState('');
  const close = () => {
    setReason('');
    problem.clear();
    onClose();
  };
  const cancel = action === 'cancel';
  return (
    <Modal
      open={action !== null}
      title={t(cancel ? 'changes.bulk.cancel_title' : 'changes.bulk.delete_title', {
        count: ids.length,
      })}
      okText={t(cancel ? 'changes.bulk.cancel_ok' : 'changes.bulk.delete_ok')}
      cancelText={t('incidents.bulk.cancel')}
      okButtonProps={{
        danger: true,
        disabled: cancel && reason.trim() === '',
        'data-testid': 'chg-bulk-cancel-ok',
      }}
      confirmLoading={start.isPending}
      onCancel={close}
      onOk={() => {
        if (action === null) return;
        start.mutate(
          { action, recordIds: ids, reason: reason.trim() },
          {
            onSuccess: (job) => {
              setReason('');
              onStarted(job.id);
            },
            onError: (error) => {
              problem.show(error);
            },
          },
        );
      }}
    >
      <FormProblem problem={problem} />
      {cancel ? (
        <Form layout="vertical">
          <Form.Item
            label={t('changes.bulk.cancel_reason')}
            htmlFor="chg-bulk-cancel-reason"
            required
          >
            <Input.TextArea
              id="chg-bulk-cancel-reason"
              value={reason}
              count={lengthLimit(2000)}
              autoSize={{ minRows: 2 }}
              onChange={(e) => {
                setReason(e.target.value);
              }}
              data-testid="chg-bulk-cancel-reason"
            />
          </Form.Item>
        </Form>
      ) : (
        <Typography.Paragraph>{t('changes.bulk.delete_body')}</Typography.Paragraph>
      )}
    </Modal>
  );
}
