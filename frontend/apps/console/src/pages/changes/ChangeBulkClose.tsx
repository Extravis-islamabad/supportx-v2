import { Form, Input, Modal, Select, Typography } from 'antd';
import { useState } from 'react';

import { useStagedSettings, useStartChangeBulkClose } from '@supportx/api-client';
import { FormProblem, lengthLimit, useAppearance, useFormProblem, useLabel } from '@supportx/ui';

import { labelled } from '../incidents/labels';

/**
 * Close the picked changes together (REQ-CHG-101): one closure code and an optional closing
 * description for all. Each change still closes by its own move, so one that has open children
 * or tasks, or is not yet in review, is skipped and the drawer says why.
 */
export function ChangeBulkClose({
  ids,
  open,
  onClose,
  onStarted,
}: {
  ids: string[];
  open: boolean;
  onClose: () => void;
  onStarted: (jobId: string) => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const settings = useStagedSettings('changes');
  const start = useStartChangeBulkClose();
  const problem = useFormProblem();
  const [code, setCode] = useState<string | undefined>(undefined);
  const [text, setText] = useState('');
  const reset = () => {
    setCode(undefined);
    setText('');
    problem.clear();
  };
  return (
    <Modal
      open={open}
      title={t('changes.bulk.close_title', { count: ids.length })}
      okText={t('changes.bulk.close_ok')}
      cancelText={t('incidents.bulk.cancel')}
      okButtonProps={{ disabled: code === undefined, 'data-testid': 'chg-bulk-close-ok' }}
      confirmLoading={start.isPending}
      onCancel={() => {
        reset();
        onClose();
      }}
      onOk={() => {
        if (code === undefined) return;
        start.mutate(
          { recordIds: ids, closureCode: code, resolution: text.trim() || undefined },
          {
            onSuccess: (job) => {
              reset();
              onStarted(job.id);
            },
            onError: (error) => {
              problem.show(error);
            },
          },
        );
      }}
      data-testid="chg-bulk-close"
    >
      <Typography.Paragraph type="secondary">{t('changes.bulk.close_help')}</Typography.Paragraph>
      <Form layout="vertical">
        <Form.Item
          label={t('work_item.field.closure_code')}
          required
          htmlFor="chg-bulk-closure-code"
        >
          <Select
            id="chg-bulk-closure-code"
            value={code}
            onChange={setCode}
            data-testid="chg-bulk-closure-code"
            options={(settings.data?.closure_codes ?? [])
              .filter((c) => !c.disabled)
              .map((c) => ({
                value: c.code,
                label: labelled(c.labels, locale, () => t(`closure_code.${c.code}`)),
              }))}
          />
        </Form.Item>
        <Form.Item label={t('staged.move.closing_description')} htmlFor="chg-bulk-closing-text">
          <Input.TextArea
            id="chg-bulk-closing-text"
            rows={3}
            count={lengthLimit(2000)}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
            }}
            data-testid="chg-bulk-closing-text"
          />
        </Form.Item>
      </Form>
      <FormProblem problem={problem} />
    </Modal>
  );
}
