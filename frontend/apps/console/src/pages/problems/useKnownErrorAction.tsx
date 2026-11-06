import { Form, Input, Modal, Typography } from 'antd';
import { useState, type ReactNode } from 'react';

import { useKnownErrorFlag, type Problem } from '@supportx/api-client';
import {
  FormProblem,
  lengthLimit,
  useFormProblem,
  useLabel,
  type RecordAction,
} from '@supportx/ui';

/**
 * Mark or remove, as one action that keeps its place in the menu (REQ-PRB-036 AC2): its label
 * says which. Marking takes an optional comment, removing a required reason.
 */
export function useKnownErrorAction(item: Problem): {
  action: RecordAction;
  dialog: ReactNode;
} {
  const t = useLabel();
  const flag = useKnownErrorFlag(item.id);
  const problem = useFormProblem();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const live = item.known_error_at != null && item.known_error_retired_at == null;
  const allowed = item.operations.find((o) => o.action === 'mark_known_error')?.allowed === true;
  const close = () => {
    setOpen(false);
    setText('');
    problem.clear();
  };
  const submit = () => {
    flag.mutate(
      live
        ? { remove: true, reason: text, version: item.version }
        : { mark: true, comment: text, version: item.version },
      { onSuccess: close, onError: (error) => problem.show(error) },
    );
  };
  return {
    action: {
      key: 'known_error',
      label: t(live ? 'problems.known_error.remove' : 'problems.known_error.mark'),
      allowed,
      onClick: () => {
        setOpen(true);
      },
    },
    dialog: (
      <Modal
        open={open}
        title={t(live ? 'problems.known_error.remove' : 'problems.known_error.mark')}
        okText={t(live ? 'problems.known_error.remove_ok' : 'problems.known_error.mark_ok')}
        okButtonProps={{
          disabled: live && text.trim() === '',
          loading: flag.isPending,
          'data-testid': 'prb-known-error-ok',
        }}
        onOk={submit}
        onCancel={close}
        destroyOnHidden
      >
        <Form layout="vertical" data-testid="prb-known-error-dialog">
          {!live && (
            <Typography.Paragraph type="secondary">
              {t('problems.known_error.mark_hint')}
            </Typography.Paragraph>
          )}
          <Form.Item
            label={t(live ? 'problems.known_error.reason' : 'problems.known_error.comment')}
            required={live}
          >
            <Input.TextArea
              rows={3}
              count={lengthLimit(1000)}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
              }}
              data-testid="prb-known-error-text"
            />
          </Form.Item>
          <FormProblem problem={problem} />
        </Form>
      </Modal>
    ),
  };
}
