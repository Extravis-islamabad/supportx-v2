import { Flex, Form, Input, Modal, Switch, Typography } from 'antd';
import { useState } from 'react';

import {
  useFieldSensitivity,
  useSetFieldSensitivity,
  type CustomField,
  type FieldSealState,
} from '@supportx/api-client';
import {
  FormProblem,
  lengthLimit,
  ToneTag,
  useFormProblem,
  useLabel,
  type Tone,
} from '@supportx/ui';

const TONES: Record<FieldSealState, Tone> = {
  plain: 'info',
  sealing: 'warning',
  sealed: 'success',
  opening: 'warning',
};

/** Where a field's stored values stand (beside the index tag in the list, and here). */
export function SealStateTag({ field, testId }: { field: CustomField; testId: string }) {
  const t = useLabel();
  if (field.seal_state === 'plain') return null;
  return (
    <ToneTag tone={TONES[field.seal_state]} testId={testId}>
      {t(`custom_field_seal_state.${field.seal_state}`)}
    </ToneTag>
  );
}

/**
 * Sensitive (WP-057 S3b-2b, REQ-SEC-040): values sealed at rest, found by exact value only.
 * Its own route, never the editor's draft or save bar (lane A). On starts sealing at once;
 * off is the riskier way, so it asks for a reason and the field's name typed back, and says
 * how many records' values become readable at rest (lane B, the coordinator).
 */
export function SensitiveSetting({ field }: { field: CustomField }) {
  const t = useLabel();
  const impact = useFieldSensitivity(field.id);
  const change = useSetFieldSensitivity();
  const problem = useFormProblem();
  const [turningOff, setTurningOff] = useState(false);
  const [reason, setReason] = useState('');
  const [confirmName, setConfirmName] = useState('');
  const name = field.labels.en ?? field.key;
  const records = impact.data?.records ?? 0;
  const close = () => {
    setTurningOff(false);
    setReason('');
    setConfirmName('');
    problem.clear();
  };
  const send = (sensitive: boolean) => {
    problem.clear();
    change.mutate(
      {
        id: field.id,
        version: impact.data?.version ?? field.version,
        sensitive,
        ...(sensitive ? {} : { reason: reason.trim(), confirmName: confirmName.trim() }),
      },
      { onSuccess: close, onError: (error) => problem.show(error) },
    );
  };
  const named = confirmName.trim().toLocaleLowerCase() === name.trim().toLocaleLowerCase();
  return (
    <Flex vertical gap={8} data-testid="cf-sensitive">
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        {t('custom_fields.sensitive_help')}
      </Typography.Paragraph>
      <Flex gap={8} align="center" wrap>
        <Switch
          checked={field.sensitive}
          loading={change.isPending}
          aria-labelledby="cf-sensitive-label"
          onChange={(next) => {
            if (next) send(true);
            else setTurningOff(true);
          }}
          data-testid="cf-sensitive-switch"
        />
        <Typography.Text id="cf-sensitive-label">{t('custom_fields.sensitive')}</Typography.Text>
        <SealStateTag field={field} testId="cf-editor-seal-state" />
      </Flex>
      {(field.seal_state === 'sealing' || field.seal_state === 'opening') && (
        <Typography.Text type="secondary" data-testid="cf-sensitive-moving">
          {t(`custom_fields.sensitive_${field.seal_state}_help`)}
        </Typography.Text>
      )}
      {!turningOff && <FormProblem problem={problem} />}
      <Modal
        open={turningOff}
        title={t('custom_fields.sensitive_off_title', { name })}
        okText={t('custom_fields.sensitive_off_ok')}
        okButtonProps={{
          danger: true,
          disabled: reason.trim() === '' || !named,
          loading: change.isPending,
          'data-testid': 'cf-sensitive-off-ok',
        }}
        onOk={() => {
          send(false);
        }}
        onCancel={close}
        destroyOnHidden
      >
        <Form layout="vertical" data-testid="cf-sensitive-off">
          <Typography.Paragraph data-testid="cf-sensitive-off-impact">
            {t('custom_fields.sensitive_off_impact', { count: records })}
          </Typography.Paragraph>
          <Typography.Paragraph type="secondary">
            {t('custom_fields.sensitive_off_kept')}
          </Typography.Paragraph>
          <Form.Item
            label={t('custom_fields.sensitive_off_reason')}
            htmlFor="cf-off-reason"
            required
          >
            <Input.TextArea
              id="cf-off-reason"
              value={reason}
              count={lengthLimit(500)}
              autoSize={{ minRows: 2, maxRows: 5 }}
              onChange={(event) => {
                setReason(event.target.value);
              }}
              data-testid="cf-sensitive-off-reason"
            />
          </Form.Item>
          <Form.Item
            label={t('custom_fields.sensitive_off_confirm', { name })}
            htmlFor="cf-off-confirm"
            required
          >
            <Input
              id="cf-off-confirm"
              dir="auto"
              value={confirmName}
              autoComplete="off"
              onChange={(event) => {
                setConfirmName(event.target.value);
              }}
              data-testid="cf-sensitive-off-confirm"
            />
          </Form.Item>
          <FormProblem problem={problem} />
        </Form>
      </Modal>
    </Flex>
  );
}
