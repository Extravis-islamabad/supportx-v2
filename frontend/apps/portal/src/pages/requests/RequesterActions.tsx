import { Alert, Button, Card, Flex, Input, Modal, Space, Typography } from 'antd';
import { useState } from 'react';

import {
  usePortalCancel,
  usePortalEdit,
  usePortalWithdrawCancel,
  type PortalIncident,
} from '@supportx/api-client';
import { lengthLimit, reportError, RichTextField, useLabel } from '@supportx/ui';

const REASON_MAX = 2000;
const SUBJECT_MAX = 250;

/**
 * What you may still do on your own incident (WP-046b S5; REQ-INC-148), as your organisation set
 * it: cancel it, or ask to (staff decide and it stays open meanwhile); take a waiting ask back;
 * and edit the fields you may. Nothing here when none of it applies.
 */
export function RequesterActions({ item }: { item: PortalIncident }) {
  const t = useLabel();
  const cancel = usePortalCancel(item.id);
  const withdraw = usePortalWithdrawCancel(item.id);
  const edit = usePortalEdit(item.id);
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState('');
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(item.subject);
  const [description, setDescription] = useState(item.description ?? '');
  const mode = item.may_cancel ?? 'off';
  const fields = item.editable_fields ?? [];
  const waiting = item.cancellation ?? null;
  if (mode === 'off' && fields.length === 0 && waiting === null) return null;

  const sendCancel = () => {
    cancel.mutate(reason.trim(), {
      onSuccess: () => {
        setAsking(false);
        setReason('');
      },
      onError: reportError,
    });
  };
  const sendEdit = () => {
    const changes: Record<string, unknown> = {};
    if (fields.includes('subject') && subject !== item.subject) changes.subject = subject;
    if (fields.includes('description') && description !== (item.description ?? '')) {
      changes.description = description;
    }
    if (Object.keys(changes).length === 0) {
      setEditing(false);
      return;
    }
    edit.mutate(
      { changes, version: item.version },
      {
        onSuccess: () => {
          setEditing(false);
        },
        onError: reportError,
      },
    );
  };

  return (
    <Card data-testid="portal-requester-actions">
      <Flex vertical gap={12}>
        {waiting !== null ? (
          <Alert
            type="info"
            showIcon
            data-testid="portal-cancel-asked"
            message={t('portal.cancel.asked')}
            description={t('portal.cancel.asked_reason', { reason: waiting.reason })}
            action={
              <Button
                size="small"
                loading={withdraw.isPending}
                onClick={() => {
                  withdraw.mutate(undefined, { onError: reportError });
                }}
                data-testid="portal-cancel-withdraw"
              >
                {t('portal.cancel.withdraw')}
              </Button>
            }
          />
        ) : (
          mode !== 'off' && (
            <Space>
              <Button
                onClick={() => {
                  setAsking(true);
                }}
                data-testid="portal-cancel-open"
              >
                {t(mode === 'direct' ? 'portal.cancel.direct' : 'portal.cancel.ask')}
              </Button>
              <Typography.Text type="secondary">
                {t(mode === 'direct' ? 'portal.cancel.direct_hint' : 'portal.cancel.ask_hint')}
              </Typography.Text>
            </Space>
          )
        )}
        {fields.length > 0 && !editing && (
          <Button
            onClick={() => {
              setSubject(item.subject);
              setDescription(item.description ?? '');
              setEditing(true);
            }}
            style={{ alignSelf: 'start' }}
            data-testid="portal-edit-open"
          >
            {t('portal.edit.open')}
          </Button>
        )}
        {editing && (
          <Flex vertical gap={8} data-testid="portal-edit-form">
            {fields.includes('subject') && (
              <Input
                aria-label={t('portal.edit.subject')}
                value={subject}
                count={lengthLimit(SUBJECT_MAX, true)}
                onChange={(event) => {
                  setSubject(event.target.value);
                }}
                data-testid="portal-edit-subject"
              />
            )}
            {fields.includes('description') && (
              <RichTextField
                label={t('portal.edit.description')}
                value={description}
                onChange={setDescription}
                testId="portal-edit-description"
              />
            )}
            <Space>
              <Button
                onClick={() => {
                  setEditing(false);
                }}
              >
                {t('actions.cancel')}
              </Button>
              <Button
                type="primary"
                loading={edit.isPending}
                disabled={fields.includes('subject') && subject.trim() === ''}
                onClick={sendEdit}
                data-testid="portal-edit-save"
              >
                {t('portal.edit.save')}
              </Button>
            </Space>
          </Flex>
        )}
      </Flex>
      <Modal
        open={asking}
        title={t(mode === 'direct' ? 'portal.cancel.direct_title' : 'portal.cancel.ask_title')}
        onCancel={() => {
          setAsking(false);
        }}
        onOk={sendCancel}
        okText={t(mode === 'direct' ? 'portal.cancel.direct' : 'portal.cancel.ask')}
        okButtonProps={{
          loading: cancel.isPending,
          disabled: reason.trim() === '',
          danger: mode === 'direct',
          'data-testid': 'portal-cancel-send',
        }}
        destroyOnHidden
      >
        <Input.TextArea
          aria-label={t('portal.cancel.reason')}
          placeholder={t('portal.cancel.reason')}
          value={reason}
          count={lengthLimit(REASON_MAX)}
          onChange={(event) => {
            setReason(event.target.value);
          }}
          data-testid="portal-cancel-reason"
        />
      </Modal>
    </Card>
  );
}
