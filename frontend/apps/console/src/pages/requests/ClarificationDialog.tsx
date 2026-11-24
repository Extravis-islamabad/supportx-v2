import { Form, Input, Modal, Radio } from 'antd';
import { useState } from 'react';

import {
  useAskClarification,
  type Approval,
  type ClarificationAddressee,
} from '@supportx/api-client';
import { lengthLimit, reportError, useLabel } from '@supportx/ui';

const QUESTION_MAX = 2000; // as the server's (REQ-SR-037)

/**
 * Ask a question instead of deciding (WP-047a S3a; REQ-SR-037). To the requester it is a public
 * reply on the request; to the technician a private note. The stage stays pending and its
 * reminders pause until the answer comes; the approval then says "answered".
 */
export function ClarificationDialog({
  recordId,
  approval,
  hasTechnician,
  onClose,
}: {
  recordId: string;
  approval: Approval;
  hasTechnician: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const ask = useAskClarification();
  const [question, setQuestion] = useState('');
  const [addressee, setAddressee] = useState<ClarificationAddressee>('requester');
  const empty = question.trim() === '';
  return (
    <Modal
      open
      title={t('requests.clarification.ask_title')}
      okText={t('requests.clarification.send')}
      cancelText={t('actions.cancel')}
      okButtonProps={{ disabled: empty, 'data-testid': 'clarification-send' }}
      confirmLoading={ask.isPending}
      onCancel={onClose}
      onOk={() => {
        ask.mutate(
          {
            recordId,
            approvalId: approval.id,
            version: approval.version,
            question: question.trim(),
            addressee,
          },
          { onSuccess: onClose, onError: reportError },
        );
      }}
      data-testid="clarification-dialog"
    >
      <Form layout="vertical" component="div">
        <Form.Item label={t('requests.clarification.to')}>
          <Radio.Group
            value={addressee}
            onChange={(e) => {
              setAddressee(e.target.value as ClarificationAddressee);
            }}
            data-testid="clarification-addressee"
          >
            <Radio value="requester">{t('approval_clarification_addressee.requester')}</Radio>
            <Radio value="technician" disabled={!hasTechnician}>
              {t('approval_clarification_addressee.technician')}
            </Radio>
          </Radio.Group>
        </Form.Item>
        <Form.Item
          label={t('requests.clarification.question')}
          htmlFor="clarification-question"
          extra={t(
            addressee === 'requester'
              ? 'requests.clarification.public_help'
              : 'requests.clarification.private_help',
          )}
        >
          <Input.TextArea
            id="clarification-question"
            value={question}
            count={lengthLimit(QUESTION_MAX)}
            autoSize={{ minRows: 3, maxRows: 8 }}
            onChange={(e) => {
              setQuestion(e.target.value);
            }}
            data-testid="clarification-question"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
