import { DeleteOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Alert, App, Button, Flex, Input, Modal, Skeleton, Tooltip, Typography } from 'antd';
import { useState } from 'react';
import { useParams } from 'react-router';

import {
  ApiError,
  erasureKeys,
  useErasure,
  useErasureActions,
  useSession,
  useUser,
  type Erasure,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { useListChannel } from '@supportx/realtime';
import {
  ConflictDialog,
  HeaderActions,
  NoAccess,
  PropertiesPanel,
  PropertyList,
  RecordHeader,
  RecordPage,
  Tabs,
  ToneTag,
  lengthLimit,
  useAccess,
  useConflictRetry,
  useDateTime,
  useLabel,
  usePageCrumbs,
  type MoreAction,
} from '@supportx/ui';

import { ErasureHistory } from './ErasureHistory';
import { MentionsReport } from './MentionsReport';
import {
  ERASE,
  STATE_TONES,
  countLabel,
  holdingLabel,
  moduleLabel,
  sameName,
  stepLabel,
  useErasureProblem,
} from './erasureText';
import { PersonName, StepProgress } from './words';

const DECIDABLE = new Set(['requested']);

/** Why Approve is off, in words (shown in the tooltip and beneath the button), or null. */
function approveBlocked(erasure: Erasure): string | null {
  if (!DECIDABLE.has(erasure.state)) return 'people_erasure.why.decided';
  if ((erasure.report?.ports_missing.length ?? 0) > 0) return 'people_erasure.why.ports_missing';
  if (!erasure.report_ready) return 'people_erasure.why.report_building';
  if (erasure.report?.reviewed_at == null) return 'people_erasure.why.report_not_reviewed';
  return null;
}

/**
 * Admin › Erasures › one erasure (ADR-052; template A): its state and progress, the summary
 * with what stays with the anonymised person, the mentions report, and its audit history.
 * Approve is the second admin's (never the requester's: the server refuses it too), after a
 * complete, reviewed report, with the person's name typed again. Nothing here runs an erasure
 * by itself: the job starts only after an approval.
 */
export function ErasurePage() {
  const t = useLabel();
  const { id } = useParams();
  const { can } = useAccess();
  const allowed = can(ERASE);
  const queryClient = useQueryClient();
  const found = useErasure(allowed ? id : undefined);
  const erasure = found.data;
  const person = useUser(
    erasure === undefined || erasure.state === 'done' ? undefined : erasure.person_id,
    { silent: true },
  );
  const me = useSession().data?.user.id;
  useListChannel(
    allowed ? 'person_erasures' : null,
    (message) => {
      if (message.type !== 'person_erasures.changed' || id === undefined) return;
      if (!message.ids.includes(id)) return;
      void queryClient.invalidateQueries({ queryKey: erasureKeys.detail(id) });
      void queryClient.invalidateQueries({ queryKey: erasureKeys.mentions(id) });
    },
    {
      // No id in the route: nothing is shown, so nothing to catch up.
      covers: id === undefined ? [] : [erasureKeys.detail(id), erasureKeys.mentions(id)],
    },
  );
  usePageCrumbs([
    { label: t('people_erasure.title'), path: '/admin/erasures' },
    { label: t('people_erasure.record_type') },
  ]);
  const [approving, setApproving] = useState(false);
  const [rejecting, setRejecting] = useState<'reject' | 'withdraw'>();
  if (!allowed) return <NoAccess titleKey="people_erasure.title" />;
  if (found.isPending) return <Skeleton active />;
  if (erasure === undefined) {
    return <Alert type="warning" showIcon message={t('errors.erasure_not_found')} />;
  }
  const erased = erasure.state === 'done';
  const name = erased
    ? t('people_erasure.erased_person')
    : (person.data?.display_name ?? t('people_erasure.unknown_person'));
  const mine = me !== undefined && me === erasure.requested_by;
  const blocked = approveBlocked(erasure);
  const open = DECIDABLE.has(erasure.state) || erasure.state === 'approved';
  const more: MoreAction[] = open
    ? [
        mine
          ? {
              key: 'withdraw',
              label: t('people_erasure.withdraw'),
              onClick: () => {
                setRejecting('withdraw');
              },
              testId: 'erasure-withdraw',
            }
          : {
              key: 'reject',
              label: t('people_erasure.reject'),
              danger: true,
              onClick: () => {
                setRejecting('reject');
              },
              testId: 'erasure-reject',
            },
      ]
    : [];
  // The requester never sees Approve (another admin decides; the server refuses it too).
  const primary =
    mine || !DECIDABLE.has(erasure.state) ? undefined : (
      <Tooltip title={blocked === null ? undefined : t(blocked)}>
        <Button
          // Primary, not danger: a white label on dark mode's danger red fails contrast (axe); the
          // typed-name dialog's OK is the danger one (lane C's condition 2).
          type="primary"
          disabled={blocked !== null}
          onClick={() => {
            setApproving(true);
          }}
          data-testid="erasure-approve"
        >
          {t('people_erasure.approve')}
        </Button>
      </Tooltip>
    );
  return (
    <RecordPage
      testId="erasure-page"
      header={
        <RecordHeader
          icon={<DeleteOutlined />}
          displayId={t('people_erasure.record_type')}
          copyable={false}
          title={name}
          testIds={{ title: 'erasure-heading' }}
          tags={
            <ToneTag tone={STATE_TONES[erasure.state]} testId="erasure-state">
              {t(`people_erasure.state.${erasure.state}`)}
            </ToneTag>
          }
          meta={[<StepProgress key="step" step={erasure.step} steps={erasure.steps} />]}
        />
      }
      actions={
        <Flex vertical gap={4} align="flex-end">
          <HeaderActions primary={primary} more={more} testId="erasure-actions" />
          {primary !== undefined && blocked !== null && (
            <Typography.Text type="secondary" data-testid="erasure-approve-why">
              {t(blocked)}
            </Typography.Text>
          )}
          {mine && DECIDABLE.has(erasure.state) && (
            <Typography.Text type="secondary" data-testid="erasure-other-admin">
              {t('people_erasure.not_requester_note')}
            </Typography.Text>
          )}
        </Flex>
      }
      alerts={
        erasure.last_error_code !== null &&
        erasure.state === 'failed' && (
          <Alert
            type="error"
            showIcon
            role="status"
            message={stepLabel(t, erasure.last_error_code)}
            data-testid="erasure-problem"
          />
        )
      }
      panel={<ErasurePanel erasure={erasure} />}
    >
      <Tabs
        data-testid="erasure-tabs"
        items={[
          {
            key: 'summary',
            label: t('people_erasure.tab.summary'),
            children: <Summary erasure={erasure} />,
          },
          {
            key: 'mentions',
            label: t('people_erasure.tab.mentions'),
            children: (
              <MentionsReport
                erasure={erasure}
                personName={erased ? undefined : person.data?.display_name}
                personEmail={erased ? undefined : (person.data?.email ?? undefined)}
              />
            ),
          },
          {
            key: 'history',
            label: t('people_erasure.tab.history'),
            children: <ErasureHistory erasureId={erasure.id} />,
          },
        ]}
      />
      {approving && (
        <ApproveDialog
          erasure={erasure}
          name={name}
          onClose={() => {
            setApproving(false);
          }}
        />
      )}
      {rejecting !== undefined && (
        <RejectDialog
          erasure={erasure}
          kind={rejecting}
          onClose={() => {
            setRejecting(undefined);
          }}
        />
      )}
    </RecordPage>
  );
}

function ErasurePanel({ erasure }: { erasure: Erasure }) {
  const t = useLabel();
  const dates = useDateTime();
  const when = (at: string | null | undefined) =>
    at == null ? null : <span title={dates.format(at)}>{dates.relative(at)}</span>;
  return (
    <PropertiesPanel
      testId="erasure-panel"
      sections={[
        {
          key: 'details',
          title: t('people_erasure.record_type'),
          children: (
            <PropertyList
              testId="erasure-props"
              items={[
                {
                  key: 'progress',
                  label: t('people_erasure.step_now'),
                  content: <StepProgress step={erasure.step} steps={erasure.steps} />,
                  filled: true,
                },
                {
                  key: 'requested',
                  label: t('people_erasure.requested_by'),
                  content: (
                    <span>
                      <PersonName id={erasure.requested_by} /> · {when(erasure.requested_at)}
                    </span>
                  ),
                  filled: true,
                },
                {
                  key: 'expires',
                  label: t('people_erasure.expires'),
                  content: when(erasure.expires_at),
                  filled: erasure.state === 'requested',
                },
                {
                  key: 'approved',
                  label: t('people_erasure.approved_by'),
                  content: (
                    <span>
                      <PersonName id={erasure.approved_by ?? null} /> · {when(erasure.approved_at)}
                    </span>
                  ),
                  filled: erasure.approved_by != null,
                },
              ]}
            />
          ),
        },
      ]}
    />
  );
}

/** What stays with the anonymised person: counts only, by kind (D-171). */
export function Holdings({ holdings }: { holdings: Record<string, number> }) {
  const t = useLabel();
  const rows = Object.entries(holdings).filter(([, n]) => n > 0);
  if (rows.length === 0) return <span>{t('people_erasure.holdings_none')}</span>;
  return (
    <ul style={{ margin: 0, paddingInlineStart: 20 }} data-testid="erasure-holdings">
      {rows.map(([kind, n]) => (
        <li key={kind}>
          {holdingLabel(t, kind)}: <bdi dir="ltr">{n}</bdi>
        </li>
      ))}
    </ul>
  );
}

function Summary({ erasure }: { erasure: Erasure }) {
  const t = useLabel();
  const kept = Object.keys(erasure.keep_files).length;
  const counts = Object.entries(erasure.counts).filter(([, n]) => n > 0);
  return (
    <PropertyList
      testId="erasure-summary"
      items={[
        {
          key: 'reason',
          label: t('people_erasure.reason'),
          content: t(`people_erasure.reason.${erasure.reason_code}`),
          filled: true,
        },
        {
          key: 'reason_text',
          label: t('people_erasure.reason_text'),
          content: <bdi dir="auto">{erasure.reason_text ?? ''}</bdi>,
          filled: erasure.reason_text !== null && erasure.reason_text !== '',
        },
        {
          key: 'successor',
          label: t('people_erasure.successor'),
          content: <PersonName id={erasure.effective_successor_id ?? erasure.successor_id} />,
          filled: true,
        },
        {
          key: 'files',
          label: t('people_erasure.files_kept'),
          content:
            kept === 0
              ? t('people_erasure.files_kept_none')
              : t('people_erasure.files_kept_n', { n: kept }),
          filled: true,
        },
        {
          key: 'holdings',
          label: t('people_erasure.holdings'),
          content: (
            <Flex vertical gap={4}>
              <Holdings holdings={erasure.holdings ?? {}} />
              <Typography.Text type="secondary">
                {t('people_erasure.holdings_note')}
              </Typography.Text>
            </Flex>
          ),
          filled: erasure.state === 'requested' || erasure.state === 'approved',
        },
        {
          key: 'counts',
          label: t('people_erasure.counts'),
          content: (
            <ul style={{ margin: 0, paddingInlineStart: 20 }} data-testid="erasure-counts">
              {counts.map(([kind, n]) => (
                <li key={kind}>
                  {countLabel(t, kind)}: <bdi dir="ltr">{n}</bdi>
                </li>
              ))}
            </ul>
          ),
          filled: counts.length > 0,
        },
      ]}
    />
  );
}

/**
 * The second admin's approval (lane C's condition 2): before the typed name, what stays with the
 * anonymised person and any part of the product not yet searched (the coordinator's condition 3);
 * OK stays off until the name matches, and is a danger button.
 */
function ApproveDialog({
  erasure,
  name,
  onClose,
}: {
  erasure: Erasure;
  name: string;
  onClose: () => void;
}) {
  const t = useLabel();
  const list = useListFormat();
  const { message } = App.useApp();
  const { approve } = useErasureActions(erasure.id);
  const retry = useConflictRetry();
  const problemOf = useErasureProblem();
  const [typed, setTyped] = useState('');
  const [said, setSaid] = useState<string>();
  const missing = erasure.report?.ports_missing ?? [];
  const named = sameName(typed, name);
  const send = (version: number) => {
    setSaid(undefined);
    approve.mutate(
      { version, confirmName: typed.trim() },
      {
        onSuccess: () => {
          void message.success(t('people_erasure.approved'));
          onClose();
        },
        onError: (error) => {
          if (retry.take(error, send)) return;
          setSaid(problemOf(error));
        },
      },
    );
  };
  return (
    <>
      <Modal
        open
        title={t('people_erasure.approve_title', { name })}
        okText={t('people_erasure.approve_ok')}
        okButtonProps={{ danger: true, disabled: !named, 'data-testid': 'erasure-approve-ok' }}
        cancelText={t('actions.cancel')}
        confirmLoading={approve.isPending}
        onOk={() => {
          send(erasure.version);
        }}
        onCancel={onClose}
        destroyOnHidden
        data-testid="erasure-approve-dialog"
      >
        <Flex vertical gap={12}>
          <Typography.Text>{t('people_erasure.approve_explain')}</Typography.Text>
          <div>
            <Typography.Text strong>{t('people_erasure.approve_holdings')}</Typography.Text>
            <Holdings holdings={erasure.holdings ?? {}} />
          </div>
          {missing.length > 0 && (
            <Alert
              type="warning"
              showIcon
              role="status"
              data-testid="erasure-approve-missing"
              message={t('people_erasure.report.ports_missing', {
                modules: list(missing.map((m) => moduleLabel(t, m))),
              })}
            />
          )}
          <label htmlFor="erasure-approve-name">
            {t('people_erasure.confirm_label', { name })}
          </label>
          <Input
            id="erasure-approve-name"
            autoComplete="off"
            value={typed}
            onChange={(e) => {
              setTyped(e.target.value);
            }}
            data-testid="erasure-approve-name"
          />
          {said !== undefined && (
            <Alert type="error" showIcon role="alert" message={said} data-testid="erasure-said" />
          )}
        </Flex>
      </Modal>
      <ConflictDialog {...retry.dialog} />
    </>
  );
}

function RejectDialog({
  erasure,
  kind,
  onClose,
}: {
  erasure: Erasure;
  kind: 'reject' | 'withdraw';
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const { reject } = useErasureActions(erasure.id);
  const retry = useConflictRetry();
  const problemOf = useErasureProblem();
  const [reason, setReason] = useState('');
  const [said, setSaid] = useState<string>();
  const send = (version: number) => {
    setSaid(undefined);
    reject.mutate(
      { version, reason: reason.trim() === '' ? null : reason.trim() },
      {
        onSuccess: () => {
          void message.success(
            t(kind === 'withdraw' ? 'people_erasure.withdrawn' : 'people_erasure.rejected'),
          );
          onClose();
        },
        onError: (error) => {
          if (retry.take(error, send)) return;
          setSaid(error instanceof ApiError ? problemOf(error) : t('errors.internal_error'));
        },
      },
    );
  };
  return (
    <>
      <Modal
        open
        title={t(
          kind === 'withdraw' ? 'people_erasure.withdraw_title' : 'people_erasure.reject_title',
        )}
        okText={t(kind === 'withdraw' ? 'people_erasure.withdraw' : 'people_erasure.reject')}
        okButtonProps={{ danger: kind === 'reject', 'data-testid': 'erasure-reject-ok' }}
        cancelText={t('actions.cancel')}
        confirmLoading={reject.isPending}
        onOk={() => {
          send(erasure.version);
        }}
        onCancel={onClose}
        destroyOnHidden
        data-testid="erasure-reject-dialog"
      >
        <Flex vertical gap={8}>
          <label htmlFor="erasure-reject-reason">{t('people_erasure.reason_optional')}</label>
          <Input.TextArea
            id="erasure-reject-reason"
            rows={3}
            count={lengthLimit(1000)}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
            }}
            data-testid="erasure-reject-reason"
          />
          {said !== undefined && <Alert type="error" showIcon role="alert" message={said} />}
        </Flex>
      </Modal>
      <ConflictDialog {...retry.dialog} />
    </>
  );
}
