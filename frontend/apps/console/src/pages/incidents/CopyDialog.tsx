import { App, Checkbox, Form, InputNumber, Modal, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useCopyIncident,
  useIncidentCatalogue,
  type RecordCopyPart,
} from '@supportx/api-client';
import { useListFormat, type LabelParams } from '@supportx/labels';
import { reportError, useLabel } from '@supportx/ui';

// Copy an incident one or more times (WP-046a S5c; REQ-INC-033). Each copy gets a new ID, its
// history names this one and its subject says it is a copy. The fields always come; tasks when
// chosen; never the conversation, worklogs or history (AC2). The server's limit is said at the
// count when it refuses (AC3).

const PARTS: readonly RecordCopyPart[] = ['tasks', 'attachments'];
const DEFAULT_MAX = 20; // until the settings load; the server's own limit is the one that counts

export function CopyDialog({
  open,
  recordId,
  displayId,
  onClose,
}: {
  open: boolean;
  recordId: string;
  displayId: string;
  onClose: () => void;
}) {
  const t = useLabel();
  const listFormat = useListFormat();
  const { message } = App.useApp();
  const copy = useCopyIncident(recordId);
  const shownMax = useIncidentCatalogue().data?.closure.copy_limit ?? DEFAULT_MAX;
  const [count, setCount] = useState(1);
  const [parts, setParts] = useState<RecordCopyPart[]>([]);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [problem, setProblem] = useState<{ key: string; params: LabelParams } | null>(null);

  const close = () => {
    setCount(1);
    setParts([]);
    setProblem(null);
    setKey(crypto.randomUUID());
    onClose();
  };
  const submit = () => {
    setProblem(null);
    copy.mutate(
      { count, parts, key },
      {
        onSuccess: (made) => {
          void message.success(
            t('incidents.copy.made', {
              ids: listFormat(
                made.items.map((i) => i.display_id),
                'conjunction',
              ),
            }),
          );
          // Files that could not be copied now (scanning, infected, too large) stay behind.
          if (made.files_not_copied.length > 0) {
            void message.warning(
              t('incidents.copy.files_left_out', { count: made.files_not_copied.length }),
            );
          }
          close();
        },
        onError: (error) => {
          const field =
            error instanceof ApiError && error.status === 422
              ? error.fieldErrors.find((e) => e.field === 'body.count')
              : undefined;
          if (field !== undefined) {
            setProblem({ key: field.message_key, params: field.params ?? {} });
            setKey(crypto.randomUUID());
            return;
          }
          reportError(error);
        },
      },
    );
  };

  return (
    <Modal
      open={open}
      title={t('incidents.copy.title', { id: displayId })}
      okText={t('incidents.copy.confirm', { count })}
      cancelText={t('actions.cancel')}
      onOk={submit}
      onCancel={close}
      confirmLoading={copy.isPending}
      okButtonProps={{ 'data-testid': 'inc-copy-confirm' }}
      data-testid="inc-copy"
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">{t('incidents.copy.help')}</Typography.Paragraph>
      <Form layout="vertical" component="div">
        <Form.Item
          label={t('incidents.copy.count')}
          htmlFor="inc-copy-count"
          validateStatus={problem === null ? undefined : 'error'}
          help={
            problem === null
              ? t('incidents.copy.count_help', { max: shownMax })
              : t(problem.key, problem.params)
          }
        >
          <InputNumber
            id="inc-copy-count"
            min={1}
            precision={0}
            value={count}
            onChange={(next) => {
              setCount(next ?? 1);
              setProblem(null);
            }}
            data-testid="inc-copy-count"
          />
        </Form.Item>
        <Form.Item label={t('incidents.copy.with')}>
          <Checkbox.Group<RecordCopyPart>
            value={parts}
            onChange={setParts}
            options={PARTS.map((part) => ({
              value: part,
              label: t(`record_copy_part.${part}`),
            }))}
            data-testid="inc-copy-parts"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
