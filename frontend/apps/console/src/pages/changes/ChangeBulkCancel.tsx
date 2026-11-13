import { Form, Input, Modal, Typography } from 'antd';
import { useState } from 'react';

import { useStartBulk, type StagedPath } from '@supportx/api-client';
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
  base = 'changes',
}: {
  ids: string[];
  action: 'cancel' | 'delete' | null;
  onClose: () => void;
  onStarted: (jobId: string) => void;
  /** The changes' list, or the releases' (REQ-REL-057). */
  base?: StagedPath;
}) {
  const t = useLabel();
  const start = useStartBulk(base);
  const id = base === 'changes' ? 'chg' : 'rel'; // the test ids each list has had
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
      title={t(cancel ? `${base}.bulk.cancel_title` : `${base}.bulk.delete_title`, {
        count: ids.length,
      })}
      // One change or several, in the button's words too (QA 2026-11-12 F-08).
      okText={t(cancel ? `${base}.bulk.cancel_ok` : `${base}.bulk.delete_ok`, {
        count: ids.length,
      })}
      cancelText={t('incidents.bulk.cancel')}
      okButtonProps={{
        danger: true,
        disabled: cancel && reason.trim() === '',
        'data-testid': `${id}-bulk-cancel-ok`,
      }}
      confirmLoading={start.isPending}
      onCancel={close}
      onOk={() => {
        if (action === null) return;
        start.mutate(
          {
            action,
            recordIds: ids,
            changes: action === 'cancel' ? { reason_text: reason.trim() } : {},
          },
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
            label={t(`${base}.bulk.cancel_reason`)}
            htmlFor={`${id}-bulk-cancel-reason`}
            required
          >
            <Input.TextArea
              id={`${id}-bulk-cancel-reason`}
              value={reason}
              count={lengthLimit(2000)}
              autoSize={{ minRows: 2 }}
              onChange={(e) => {
                setReason(e.target.value);
              }}
              data-testid={`${id}-bulk-cancel-reason`}
            />
          </Form.Item>
        </Form>
      ) : (
        <Typography.Paragraph>{t(`${base}.bulk.delete_body`)}</Typography.Paragraph>
      )}
    </Modal>
  );
}
