import { useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Form, Input, List, Modal, Space, Typography } from 'antd';
import { useState } from 'react';

import {
  releaseKeys,
  useAckReleaseConflict,
  useRelease,
  useReleaseConflicts,
  useReleaseFreezeOverride,
  useUser,
  type ReleaseConflict,
} from '@supportx/api-client';
import { useListChannel, useTenantChannel } from '@supportx/realtime';
import {
  FormProblem,
  ToneTag,
  WriteButton,
  lengthLimit,
  useAccess,
  useAppearance,
  useDateTime,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

import { labelled } from '../incidents/labels';

/** The kind's name: an overlap says change or release (ADR-042 addendum A). */
function conflictKindName(
  t: (key: string) => string,
  c: Pick<ReleaseConflict, 'kind' | 'record_type'>,
): string {
  return t(
    c.kind === 'overlap' && c.record_type === 'release'
      ? 'change_conflict.overlap_release'
      : `change_conflict.${c.kind}`,
  );
}

/** An ack's words: free text someone typed (never a code), shown as they wrote it. */
const ackWords = (c: ReleaseConflict): string => c.ack?.reason ?? '';

function AckedBy({ id }: { id: string }) {
  const user = useUser(id);
  return <bdi dir="auto">{user.data?.display_name ?? ''}</bdi>;
}

function ReasonDialog({
  title,
  warning,
  okText,
  danger,
  saving,
  onOk,
  onClose,
  problem,
  testId,
}: {
  title: string;
  warning: string;
  okText: string;
  danger: boolean;
  saving: boolean;
  onOk: (reason: string) => void;
  onClose: () => void;
  problem: ReturnType<typeof useFormProblem>;
  testId: string;
}) {
  const t = useLabel();
  const [reason, setReason] = useState('');
  return (
    <Modal
      open
      title={title}
      okText={okText}
      okButtonProps={{
        danger,
        disabled: reason.trim() === '',
        loading: saving,
        'data-testid': `${testId}-ok`,
      }}
      onOk={() => {
        onOk(reason.trim());
      }}
      onCancel={onClose}
      destroyOnHidden
    >
      <Form layout="vertical" data-testid={testId}>
        <Alert type="warning" showIcon style={{ marginBottom: 16 }} message={warning} />
        <Form.Item label={t('releases.conflicts.reason')} required htmlFor={`${testId}-reason`}>
          <Input.TextArea
            id={`${testId}-reason`}
            rows={3}
            count={lengthLimit(500)}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
            }}
            data-testid={`${testId}-reason`}
          />
        </Form.Item>
        <FormProblem problem={problem} />
      </Form>
    </Modal>
  );
}

/**
 * A release's conflicts (WP-058b S2; REQ-REL-040, -041; ADR-042 addendum A): freezes, being
 * outside maintenance, overlapping changes and releases (named by ID and type only), and a role
 * holder booked twice. A warning can be acknowledged with a reason (it holds until either side
 * moves); blocking freezes can be passed by those holding `releases.override_freeze`, with a
 * reason. Live: a record moving, a window changing, or this release changing refetch it.
 */
export function ReleaseConflictsPanel({ id }: { id: string }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { format } = useDateTime();
  const { can } = useAccess();
  const queryClient = useQueryClient();
  const release = useRelease(id);
  const conflicts = useReleaseConflicts(id);
  const ack = useAckReleaseConflict();
  const override = useReleaseFreezeOverride();
  const ackProblem = useFormProblem();
  const overrideProblem = useFormProblem();
  const [acking, setAcking] = useState<ReleaseConflict>();
  const [overriding, setOverriding] = useState(false);
  const refetch = () => {
    void queryClient.invalidateQueries({ queryKey: releaseKeys.part(id, 'conflicts') });
  };
  useListChannel('releases', refetch);
  useListChannel('changes', refetch);
  useTenantChannel((m) => {
    if (m.type === 'work_items.change_windows_changed') refetch();
  });
  const items = conflicts.data?.items ?? [];
  if (items.length === 0) return null;
  const version = release.data?.version ?? 0;
  const freezes = [
    ...new Set(
      items.filter((c) => c.blocks && c.kind === 'freeze').flatMap((c) => c.window_id ?? []),
    ),
  ];
  const what = (c: ReleaseConflict) =>
    c.window_name !== null && c.window_name !== undefined
      ? labelled(c.window_labels, locale, () => c.window_name ?? '')
      : c.record_id
        ? t(
            c.record_type === 'release'
              ? 'changes.conflicts.another_release'
              : 'changes.conflicts.another_change',
          )
        : '';
  return (
    <>
      <Alert
        type={items.some((c) => c.blocks) ? 'error' : 'warning'}
        showIcon
        style={{ marginBottom: 12 }}
        data-testid="release-conflicts"
        message={t('changes.conflicts.title', { count: items.length })}
        action={
          freezes.length > 0 && can('releases.override_freeze') ? (
            <Button
              size="small"
              danger
              onClick={() => {
                overrideProblem.clear();
                setOverriding(true);
              }}
              data-testid="release-freeze-override"
            >
              {t('changes.freeze.override')}
            </Button>
          ) : undefined
        }
        description={
          <List
            size="small"
            dataSource={items}
            renderItem={(c) => (
              <List.Item key={c.key} data-testid={`release-conflict-${c.kind}`}>
                <Space wrap>
                  <ToneTag tone={c.blocks ? 'error' : c.ack ? 'default' : 'warning'}>
                    {conflictKindName(t, c)}
                  </ToneTag>
                  {what(c) !== '' && <span>{what(c)}</span>}
                  <span>{`${format(c.starts_at)} – ${format(c.ends_at)}`}</span>
                  {c.blocks && (
                    <Typography.Text type="danger">
                      {t('releases.conflicts.blocks')}
                    </Typography.Text>
                  )}
                  {c.ack ? (
                    <Typography.Text type="secondary" data-testid="release-conflict-acked">
                      {t('releases.conflicts.acked')} <AckedBy id={c.ack.acked_by} />
                      {' · '}
                      <bdi dir="auto">{ackWords(c)}</bdi>
                    </Typography.Text>
                  ) : (
                    !c.blocks && (
                      <WriteButton
                        size="small"
                        onClick={() => {
                          ackProblem.clear();
                          setAcking(c);
                        }}
                        data-testid={`release-conflict-ack-${c.kind}`}
                      >
                        {t('releases.conflicts.ack')}
                      </WriteButton>
                    )
                  )}
                </Space>
              </List.Item>
            )}
          />
        }
      />
      {acking !== undefined && (
        <ReasonDialog
          title={t('releases.conflicts.ack_title')}
          warning={t('releases.conflicts.ack_warning')}
          okText={t('releases.conflicts.ack')}
          danger={false}
          saving={ack.isPending}
          problem={ackProblem}
          testId="release-ack"
          onClose={() => {
            setAcking(undefined);
          }}
          onOk={(reason) => {
            ack.mutate(
              { id, version, key: acking.key, reason },
              {
                onSuccess: () => {
                  setAcking(undefined);
                },
                onError: (error) => {
                  ackProblem.show(error);
                },
              },
            );
          }}
        />
      )}
      {overriding && (
        <ReasonDialog
          title={t('releases.freeze.override_title')}
          warning={t('releases.freeze.override_warning', { count: freezes.length })}
          okText={t('changes.freeze.override_confirm')}
          danger
          saving={override.isPending}
          problem={overrideProblem}
          testId="release-override"
          onClose={() => {
            setOverriding(false);
          }}
          onOk={(reason) => {
            override.mutate(
              { id, version, reason, windowIds: freezes },
              {
                onSuccess: () => {
                  setOverriding(false);
                },
                onError: (error) => {
                  overrideProblem.show(error);
                },
              },
            );
          }}
        />
      )}
    </>
  );
}
