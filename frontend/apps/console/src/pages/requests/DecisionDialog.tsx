import { Checkbox, Form, Input, Modal } from 'antd';
import { useState } from 'react';

import type { ApprovalDecision } from '@supportx/api-client';
import { lengthLimit, useLabel } from '@supportx/ui';

const COMMENT_MAX = 4000;

/** The comment dialog of one decision: a rejection needs a reason, an approval may need one. */
export function DecisionDialog({
  decision,
  commentsRequired,
  pending,
  problems,
  onSend,
  onClose,
}: {
  decision: ApprovalDecision['decision'];
  commentsRequired: boolean;
  pending: boolean;
  problems: string[];
  onSend: (comment: string, isPrivate: boolean) => void;
  onClose: () => void;
}) {
  const t = useLabel();
  const [comment, setComment] = useState('');
  const [isPrivate, setPrivate] = useState(false);
  const needed = decision === 'reject' || commentsRequired;
  const ready = !needed || comment.trim() !== '';
  return (
    <Modal
      open
      title={t(decision === 'approve' ? 'requests.approve' : 'requests.reject')}
      okText={t(decision === 'approve' ? 'requests.approve' : 'requests.reject')}
      okButtonProps={{
        disabled: !ready,
        loading: pending,
        danger: decision === 'reject',
      }}
      cancelText={t('actions.cancel')}
      onOk={() => {
        onSend(comment.trim(), isPrivate);
      }}
      onCancel={onClose}
    >
      <Form layout="vertical">
        <Form.Item
          label={t(decision === 'reject' ? 'requests.reject_reason' : 'requests.decision_comment')}
          htmlFor="approval-comment"
          required={needed}
          validateStatus={problems.length > 0 ? 'error' : undefined}
          help={problems.length > 0 ? problems.join(' ') : undefined}
        >
          <Input.TextArea
            id="approval-comment"
            data-testid="approval-comment"
            value={comment}
            count={lengthLimit(COMMENT_MAX)}
            autoSize={{ minRows: 3 }}
            onChange={(e) => {
              setComment(e.target.value);
            }}
          />
        </Form.Item>
        <Checkbox
          checked={isPrivate}
          onChange={(e) => {
            setPrivate(e.target.checked);
          }}
          data-testid="approval-private"
        >
          {t('requests.private_comment')}
        </Checkbox>
      </Form>
    </Modal>
  );
}
