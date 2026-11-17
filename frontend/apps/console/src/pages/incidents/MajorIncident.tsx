import { FireOutlined } from '@ant-design/icons';
import { Form, Input, Modal, Tag, Typography } from 'antd';
import { useState } from 'react';

import { ApiError, useMajorChange, type Incident } from '@supportx/api-client';
import { lengthLimit, reportError, useLabel } from '@supportx/ui';

// WP-046b S4 (REQ-INC-141): the major incident marker, and declaring or ending it with a reason.

const REASON_MAX = 500;

/** The marker on a major incident: the record's header and the lists (live with the record). */
export function MajorTag({ major }: { major: boolean | undefined }) {
  const t = useLabel();
  if (major !== true) return null;
  return (
    <Tag color="red" icon={<FireOutlined />} data-testid="inc-major-tag">
      {t('incidents.major.marker')}
    </Tag>
  );
}

/** Declare the incident major, or end that, with a reason the server keeps out of history. */
export function MajorDialog({
  item,
  open,
  onClose,
}: {
  item: Pick<Incident, 'id' | 'display_id' | 'version' | 'major'>;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const change = useMajorChange(item.id);
  const ending = item.major;
  const [reason, setReason] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const close = () => {
    setReason('');
    setProblem(null);
    onClose();
  };
  return (
    <Modal
      open={open}
      title={t(ending ? 'incidents.major.end_title' : 'incidents.major.declare_title', {
        id: item.display_id,
      })}
      okText={t(ending ? 'incidents.major.end' : 'incidents.major.declare')}
      cancelText={t('actions.cancel')}
      okButtonProps={{
        disabled: reason.trim() === '',
        danger: !ending,
        loading: change.isPending,
        'data-testid': 'inc-major-confirm',
      }}
      onCancel={close}
      destroyOnHidden
      onOk={() => {
        change.mutate(
          { reason: reason.trim(), version: item.version, end: ending },
          {
            onSuccess: close,
            onError: (error) => {
              const field =
                error instanceof ApiError && error.status === 422
                  ? error.fieldErrors.find((e) => e.field.endsWith('reason'))
                  : undefined;
              if (field !== undefined) {
                setProblem(t(field.message_key, field.params ?? {}));
                return;
              }
              reportError(error);
            },
          },
        );
      }}
      data-testid="inc-major-dialog"
    >
      <Typography.Paragraph type="secondary">
        {t(ending ? 'incidents.major.end_help' : 'incidents.major.declare_help')}
      </Typography.Paragraph>
      <Form layout="vertical" component="div">
        <Form.Item
          label={t('incidents.major.reason')}
          htmlFor="inc-major-reason"
          required
          validateStatus={problem === null ? undefined : 'error'}
          help={problem ?? undefined}
        >
          <Input.TextArea
            id="inc-major-reason"
            value={reason}
            count={lengthLimit(REASON_MAX, true)}
            autoSize={{ minRows: 3, maxRows: 6 }}
            onChange={(event) => {
              setReason(event.target.value);
              setProblem(null);
            }}
            data-testid="inc-major-reason"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
