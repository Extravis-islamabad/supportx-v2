import { Form, Input, Modal, Select, Typography } from 'antd';
import { useState } from 'react';

import { useStagedSettings, useStartBulk, type StagedPath } from '@supportx/api-client';
import { FormProblem, lengthLimit, useAppearance, useFormProblem, useLabel } from '@supportx/ui';

import { labelled } from '../incidents/labels';

/**
 * Close the picked changes (or releases: `base`) together (REQ-CHG-101, REQ-REL-057): one
 * closure code, the type's own, and an optional closing description for all. Each record still
 * closes by its own move, so one with open work, or not yet in review, is skipped and the drawer
 * says why.
 */
export function ChangeBulkClose({
  ids,
  open,
  onClose,
  onStarted,
  base = 'changes',
}: {
  ids: string[];
  open: boolean;
  onClose: () => void;
  onStarted: (jobId: string) => void;
  base?: StagedPath;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const settings = useStagedSettings(base);
  const start = useStartBulk(base);
  const id = base === 'changes' ? 'chg' : 'rel'; // the test ids each list has had
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
      title={t(`${base}.bulk.close_title`, { count: ids.length })}
      okText={t(`${base}.bulk.close_ok`)}
      cancelText={t('incidents.bulk.cancel')}
      okButtonProps={{ disabled: code === undefined, 'data-testid': `${id}-bulk-close-ok` }}
      confirmLoading={start.isPending}
      onCancel={() => {
        reset();
        onClose();
      }}
      onOk={() => {
        if (code === undefined) return;
        start.mutate(
          {
            action: 'close',
            recordIds: ids,
            changes: {
              closure_code: code,
              ...(text.trim() ? { resolution: text.trim() } : {}),
            },
          },
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
      data-testid={`${id}-bulk-close`}
    >
      <Typography.Paragraph type="secondary">{t(`${base}.bulk.close_help`)}</Typography.Paragraph>
      <Form layout="vertical">
        <Form.Item
          label={t('work_item.field.closure_code')}
          required
          htmlFor={`${id}-bulk-closure-code`}
        >
          <Select
            id={`${id}-bulk-closure-code`}
            value={code}
            onChange={setCode}
            data-testid={`${id}-bulk-closure-code`}
            options={(settings.data?.closure_codes ?? [])
              .filter((c) => !c.disabled)
              .map((c) => ({
                value: c.code,
                label: labelled(c.labels, locale, () => t(`closure_code.${c.code}`)),
              }))}
          />
        </Form.Item>
        <Form.Item label={t('staged.move.closing_description')} htmlFor={`${id}-bulk-closing-text`}>
          <Input.TextArea
            id={`${id}-bulk-closing-text`}
            rows={3}
            count={lengthLimit(2000)}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
            }}
            data-testid={`${id}-bulk-closing-text`}
          />
        </Form.Item>
      </Form>
      <FormProblem problem={problem} />
    </Modal>
  );
}
