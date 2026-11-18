import { Alert, App, Flex, Input, Modal, Skeleton, Switch, Typography } from 'antd';
import { useState } from 'react';

import { useLegalHold, useLegalHoldActions, type UserDetail } from '@supportx/api-client';
import {
  ConflictDialog,
  SettingsCard,
  lengthLimit,
  useAccess,
  useConflictRetry,
  useDateTime,
  useLabel,
} from '@supportx/ui';

import { ERASE, MANAGE_HOLDS, useErasureProblem } from './erasureText';
import { PersonName } from './words';

const REASON_MAX = 1000;

/**
 * PersonDrawer › Privacy › Legal hold (ADR-052; the coordinator's condition 1, lane C's 6): a held
 * person can't be erased. Shown with the holds right or the erase right; only the holds right
 * changes it. Putting it on and lifting it each need a reason (the audit entry's); lifting also
 * a confirmation with a plain warning, and a recent sign-in (the shared pop-up asks). If-Match is
 * the person's version from the hold's own read.
 */
export function LegalHoldSection({ user }: { user: UserDetail }) {
  const t = useLabel();
  const dates = useDateTime();
  const { can } = useAccess();
  const manage = can(MANAGE_HOLDS);
  const shown = manage || can(ERASE);
  const found = useLegalHold(user.id, shown);
  const [asking, setAsking] = useState<'set' | 'lift'>();
  if (!shown) return null;
  const hold = found.data;
  // What the admin wrote when placing it: free text, never a code.
  const heldFor = hold?.reason ?? '';
  const labelId = `legal-hold-label-${user.id}`;
  return (
    <SettingsCard
      title={t('people_erasure.hold.title')}
      description={t('people_erasure.hold.explain')}
      testId="person-legal-hold"
    >
      {hold === undefined ? (
        <Skeleton active paragraph={{ rows: 1 }} />
      ) : (
        <Flex vertical gap={8}>
          <Flex gap={8} align="center">
            <Switch
              checked={hold.held}
              disabled={!manage}
              aria-labelledby={labelId}
              onChange={(next) => {
                setAsking(next ? 'set' : 'lift');
              }}
              data-testid="legal-hold-switch"
            />
            <span id={labelId}>{t('people_erasure.hold.switch')}</span>
          </Flex>
          {hold.held && (
            <Flex vertical gap={4} data-testid="legal-hold-details">
              <Typography.Text type="secondary">
                {t('people_erasure.hold.placed_by')}: <PersonName id={hold.held_by ?? null} />
                {hold.held_at != null && (
                  <>
                    {' · '}
                    <span title={dates.format(hold.held_at)}>{dates.relative(hold.held_at)}</span>
                  </>
                )}
              </Typography.Text>
              {heldFor !== '' && (
                <Typography.Text type="secondary">
                  {t('people_erasure.hold.reason')}: <bdi dir="auto">{heldFor}</bdi>
                </Typography.Text>
              )}
            </Flex>
          )}
        </Flex>
      )}
      {asking !== undefined && hold !== undefined && (
        <HoldDialog
          user={user}
          kind={asking}
          version={hold.version}
          onClose={() => {
            setAsking(undefined);
          }}
        />
      )}
    </SettingsCard>
  );
}

function HoldDialog({
  user,
  kind,
  version,
  onClose,
}: {
  user: UserDetail;
  kind: 'set' | 'lift';
  version: number;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const { hold, lift } = useLegalHoldActions(user.id);
  const retry = useConflictRetry();
  const problemOf = useErasureProblem();
  const [reason, setReason] = useState('');
  const [said, setSaid] = useState<string>();
  const action = kind === 'set' ? hold : lift;
  const send = (at: number) => {
    setSaid(undefined);
    action.mutate(
      { version: at, reason: reason.trim() },
      {
        onSuccess: () => {
          void message.success(
            t(kind === 'set' ? 'people_erasure.hold.set_done' : 'people_erasure.hold.lift_done'),
          );
          onClose();
        },
        onError: (error) => {
          if (retry.take(error, send)) return;
          setSaid(problemOf(error));
        },
      },
    );
  };
  const name = user.display_name;
  return (
    <>
      <Modal
        open
        title={t(
          kind === 'set' ? 'people_erasure.hold.set_title' : 'people_erasure.hold.lift_title',
          { name },
        )}
        okText={t(kind === 'set' ? 'people_erasure.hold.set_ok' : 'people_erasure.hold.lift_ok')}
        okButtonProps={{ danger: kind === 'lift', disabled: reason.trim() === '' }}
        cancelText={t('actions.cancel')}
        confirmLoading={action.isPending}
        onOk={() => {
          send(version);
        }}
        onCancel={onClose}
        destroyOnHidden
        data-testid="legal-hold-dialog"
      >
        <Flex vertical gap={8}>
          {kind === 'lift' && (
            <Alert
              type="warning"
              showIcon
              message={t('people_erasure.hold.lift_warning')}
              data-testid="legal-hold-lift-warning"
            />
          )}
          <label htmlFor="legal-hold-reason">{t('people_erasure.hold.reason')}</label>
          <Input.TextArea
            id="legal-hold-reason"
            rows={3}
            count={lengthLimit(REASON_MAX)}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
            }}
            data-testid="legal-hold-reason"
          />
          <Typography.Text type="secondary">{t('people_erasure.reason_text_hint')}</Typography.Text>
          {said !== undefined && <Alert type="error" showIcon role="alert" message={said} />}
        </Flex>
      </Modal>
      <ConflictDialog {...retry.dialog} />
    </>
  );
}
