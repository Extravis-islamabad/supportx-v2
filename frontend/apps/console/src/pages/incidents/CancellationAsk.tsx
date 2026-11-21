import {
  useDecideCancellation,
  useIncidentCatalogue,
  useIncidentCancellationRequest,
  type Incident,
} from '@supportx/api-client';
import { AlertStrip, lengthLimit, reportError, useAppearance, useLabel } from '@supportx/ui';
import { Button, Input, Modal, Select, Space, Typography } from 'antd';
import { useState } from 'react';

import { labelled } from './labels';

/**
 * A requester's waiting ask to cancel (WP-046b S5; REQ-INC-148 AC1), on the record: what they
 * asked and why, and for whoever decides (the assignee; with none, whoever may edit it) Approve
 * or Decline. Approving runs the ordinary cancel as you, with their reason, asking for the
 * cancel's own reason code when it needs one; declining sends your note to the requester. The
 * record's live updates refresh it (its query is under the record's).
 */
export function CancellationAsk({ item }: { item: Incident }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const ask = useIncidentCancellationRequest(item.id);
  const catalogue = useIncidentCatalogue();
  const decide = useDecideCancellation(item.id);
  const [dialog, setDialog] = useState<'approve' | 'decline' | null>(null);
  const [code, setCode] = useState<string>();
  const [note, setNote] = useState('');
  const waiting = ask.data;
  if (waiting === undefined || waiting === null) return null;
  const cancel = item.actions.find((a) => a.action === 'cancel');
  const list = cancel !== undefined && cancel.reason_mode !== 'none' ? cancel.reason_list : null;
  const codeRequired = cancel?.reason_mode === 'required';
  const options = (catalogue.data?.reasons ?? [])
    .filter((r) => r.list === list && !r.disabled)
    .map((r) => ({
      value: r.code,
      label: labelled(r.labels, locale, () => t(`reason.${r.list}.${r.code}`)),
    }));
  const close = () => {
    setDialog(null);
    setCode(undefined);
    setNote('');
  };
  const send = () => {
    decide.mutate(
      dialog === 'approve'
        ? { approve: true, ...(code === undefined ? {} : { reason_code: code }) }
        : { approve: false, note },
      { onSuccess: close, onError: reportError },
    );
  };
  return (
    <>
      <AlertStrip
        testId="inc-cancellation-ask"
        alerts={[
          {
            key: 'cancellation-ask',
            type: 'info',
            dismissible: false,
            // Who decides it, so "nobody can decide yet" is never silent (S5 condition 1).
            message: (
              <>
                {t('incidents.cancellation_ask.message', { reason: waiting.reason })}{' '}
                <Typography.Text type="secondary" data-testid="inc-cancellation-deciders">
                  {t(`cancellation_deciders.${waiting.deciders}`)}
                </Typography.Text>
              </>
            ),
            action: waiting.may_decide ? (
              <Space>
                <Button
                  size="small"
                  type="primary"
                  onClick={() => {
                    setDialog('approve');
                  }}
                  data-testid="inc-cancellation-approve"
                >
                  {t('incidents.cancellation_ask.approve')}
                </Button>
                <Button
                  size="small"
                  onClick={() => {
                    setDialog('decline');
                  }}
                  data-testid="inc-cancellation-decline"
                >
                  {t('incidents.cancellation_ask.decline')}
                </Button>
              </Space>
            ) : undefined,
          },
        ]}
      />
      <Modal
        open={dialog !== null}
        title={t(
          dialog === 'approve'
            ? 'incidents.cancellation_ask.approve_title'
            : 'incidents.cancellation_ask.decline_title',
        )}
        onCancel={close}
        onOk={send}
        okText={t(
          dialog === 'approve'
            ? 'incidents.cancellation_ask.approve'
            : 'incidents.cancellation_ask.decline',
        )}
        okButtonProps={{
          loading: decide.isPending,
          disabled: dialog === 'approve' ? codeRequired && code === undefined : note.trim() === '',
          'data-testid': 'inc-cancellation-ok',
        }}
        destroyOnHidden
      >
        {dialog === 'approve' ? (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Typography.Text>
              {t('incidents.cancellation_ask.approve_body', { reason: waiting.reason })}
            </Typography.Text>
            {options.length > 0 && (
              <Select
                aria-label={t('incidents.cancellation_ask.reason_code')}
                placeholder={t('incidents.cancellation_ask.reason_code')}
                value={code}
                onChange={setCode}
                options={options}
                style={{ width: '100%' }}
                data-testid="inc-cancellation-code"
              />
            )}
          </Space>
        ) : (
          <Input.TextArea
            aria-label={t('incidents.cancellation_ask.note')}
            placeholder={t('incidents.cancellation_ask.note')}
            value={note}
            count={lengthLimit(2000)}
            onChange={(event) => {
              setNote(event.target.value);
            }}
            data-testid="inc-cancellation-note"
          />
        )}
      </Modal>
    </>
  );
}
