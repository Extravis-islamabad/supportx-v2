import { App, Modal, Typography } from 'antd';
import { useState } from 'react';

import { useMessageIncidentRequesters, useSession } from '@supportx/api-client';
import { FormProblem, RichTextField, useFormProblem, useLabel } from '@supportx/ui';

/**
 * One message to every requester of the linked incidents (REQ-PRB-052 AC3): it is sent as a
 * public reply on each incident the technician may reply on, so each requester gets it through
 * their own incident, with its delivery state there. Nothing internal is added to it.
 */
export function MessageRequestersDialog({
  problemId,
  open,
  onClose,
}: {
  problemId: string;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const me = useSession().data?.user.id;
  const send = useMessageIncidentRequesters(problemId);
  const problem = useFormProblem();
  const [html, setHtml] = useState('');
  const close = () => {
    setHtml('');
    problem.clear();
    onClose();
  };
  return (
    <Modal
      open={open}
      title={t('problems.message.title')}
      okText={t('problems.message.send')}
      okButtonProps={{
        disabled: html.replace(/<[^>]*>/g, '').trim() === '',
        loading: send.isPending,
        'data-testid': 'prb-message-send',
      }}
      onOk={() => {
        send.mutate(html, {
          onSuccess: (done) => {
            void message.success(
              t('problems.message.sent', { count: done.sent_to.length, skipped: done.skipped }),
            );
            close();
          },
          onError: (error) => problem.show(error),
        });
      }}
      onCancel={close}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">{t('problems.message.explain')}</Typography.Paragraph>
      <RichTextField
        label={t('problems.message.body')}
        value={html}
        onChange={setHtml}
        testId="prb-message-body"
        imageOwnerId={me}
      />
      <FormProblem problem={problem} />
    </Modal>
  );
}
