import { Button, List, Modal, Space, Typography } from 'antd';
import { useState } from 'react';

import { useApprovals, type Approval, type CatalogQuestion } from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import {
  EmptyText,
  ToneTag,
  useAnswerWords,
  useAppearance,
  useDateTime,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { useDecision } from './useDecision';
type Tone = 'info' | 'success' | 'warning' | 'error';
const TONE: Record<Approval['state'], Tone> = {
  pending: 'warning',
  approved: 'success',
  rejected: 'error',
  withdrawn: 'info',
  not_needed: 'info',
  skipped: 'info', // WP-047a S2a: the stage's condition did not hold
};

type Condition = Record<string, unknown>;

/**
 * A skipped stage's condition in words (REQ-SR-032 AC2): each field by its question's label and
 * each value as the form shows it, never the stored keys or codes (rule 5d).
 */
function useConditionWords(questions: CatalogQuestion[]): (c: Condition) => string {
  const t = useLabel();
  const { locale } = useAppearance();
  const answerWords = useAnswerWords();
  const list = useListFormat(); // the language's own "and" / "or" lists, never a hand join
  const describe = (c: Condition): string => {
    const all = (key: string) => (Array.isArray(c[key]) ? (c[key] as Condition[]) : null);
    const and = all('and');
    if (and) return list(and.map(describe), 'conjunction');
    const or = all('or');
    if (or) return list(or.map(describe), 'disjunction');
    if (c.not != null && typeof c.not === 'object') {
      return t('requests.condition_not', { text: describe(c.not as Condition) });
    }
    const key = typeof c.field === 'string' ? c.field : '';
    const question = questions.find((q) => q.key === key);
    const field =
      key === 'quantity'
        ? t('requests.condition_quantity')
        : question
          ? (question.label[locale] ?? question.label.en ?? '')
          : t('requests.condition_removed_question');
    const words = (v: unknown) =>
      question
        ? answerWords(question, v)
        : typeof v === 'string' || typeof v === 'number'
          ? String(v)
          : '';
    const value = Array.isArray(c.value) ? list(c.value.map(words), 'disjunction') : words(c.value);
    return t('requests.condition_leaf', { field, op: t(`rule_op.${String(c.op)}`), value });
  };
  return describe;
}

/**
 * A request's approvals (WP-030 s2, REQ-SR-024): every approver's entry with its decision,
 * when, where and the comment (a private one only for staff), why it went to a backup or the
 * administrators, and Approve / Reject for the approver (REQ-SR-025). Live: the record channel's
 * approvals signal refetches it (the page invalidates the record's queries).
 */
export function ApprovalsPanel({
  recordId,
  questions = [],
}: {
  recordId: string;
  /** The item's questions, to say a skipped stage's condition in words (WP-047a S2a). */
  questions?: CatalogQuestion[];
}) {
  const t = useLabel();
  const conditionWords = useConditionWords(questions);
  const { format } = useDateTime();
  const approvals = useApprovals(recordId);
  const { dialog, start } = useDecision(recordId);
  const people = approvals.data?.people ?? {};
  const name = (id: string | null | undefined) =>
    id == null ? t('requests.approval_admins') : (people[id]?.display_name ?? '');
  const items = approvals.data?.items ?? [];
  const staged = new Set(items.map((a) => a.stage)).size > 1;
  if (approvals.isLoading) return null;
  return (
    <>
      <List
        header={<Typography.Text strong>{t('requests.approvals')}</Typography.Text>}
        bordered
        dataSource={items}
        data-testid="sr-approvals"
        locale={{ emptyText: <EmptyText>{t('requests.no_approvals')}</EmptyText> }}
        renderItem={(a) => (
          <List.Item
            key={a.id}
            data-testid={`sr-approval-${a.id}`}
            actions={
              a.can_decide
                ? [
                    <WriteButton
                      key="approve"
                      type="primary"
                      onClick={() => {
                        start(a, 'approve');
                      }}
                      data-testid="approval-approve"
                    >
                      {t('requests.approve')}
                    </WriteButton>,
                    <WriteButton
                      key="reject"
                      danger
                      onClick={() => {
                        start(a, 'reject');
                      }}
                      data-testid="approval-reject"
                    >
                      {t('requests.reject')}
                    </WriteButton>,
                  ]
                : []
            }
          >
            <Space direction="vertical" size={2}>
              <Space wrap>
                {staged && (
                  <Typography.Text strong data-testid="approval-stage">
                    {t('requests.stage_n', { n: a.stage })}
                  </Typography.Text>
                )}
                {a.state !== 'skipped' && <bdi>{name(a.approver_id)}</bdi>}
                {a.state !== 'skipped' && (
                  <Typography.Text type="secondary">
                    {t(`approval_origin.${a.origin}`)}
                  </Typography.Text>
                )}
                {a.branch != null && (
                  <ToneTag tone="info">{t('requests.runs_in_parallel')}</ToneTag>
                )}
                <ToneTag tone={TONE[a.state]} testId="approval-state">
                  {t(`approval_state.${a.state}`)}
                </ToneTag>
                {a.self_approved && <ToneTag tone="warning">{t('requests.self_approved')}</ToneTag>}
              </Space>
              {a.skip_reason != null && (
                <Typography.Text type="secondary" data-testid="approval-skip-reason">
                  {t(`approval_skip_reason.${a.skip_reason}`)}
                  {a.condition != null &&
                    ` · ${t('requests.applies_when', { condition: conditionWords(a.condition) })}`}
                </Typography.Text>
              )}
              {a.route_reason != null && (
                <Typography.Text type="secondary" data-testid="approval-route-reason">
                  {t(`approval_route_reason.${a.route_reason}`)}
                </Typography.Text>
              )}
              {a.decided_at != null && (
                <Typography.Text type="secondary">
                  {t('requests.decided_by', {
                    name: name(a.decided_by),
                    when: format(a.decided_at),
                    channel: a.channel == null ? '' : t(`approval_channel.${a.channel}`),
                  })}
                </Typography.Text>
              )}
              {a.comment != null && (
                <Typography.Paragraph
                  style={{ marginBottom: 0 }}
                  data-testid="approval-comment-text"
                >
                  <bdi>{a.comment}</bdi>
                  {a.comment_private && (
                    <Typography.Text type="secondary">
                      {' '}
                      · {t('requests.private_comment')}
                    </Typography.Text>
                  )}
                </Typography.Paragraph>
              )}
            </Space>
          </List.Item>
        )}
      />
      {dialog}
    </>
  );
}

/** Withdraw while it waits (REQ-SR-061): the requester or the person it is for. */
export function WithdrawButton({
  onWithdraw,
  pending,
}: {
  onWithdraw: () => void;
  pending: boolean;
}) {
  const t = useLabel();
  const [asking, setAsking] = useState(false);
  return (
    <>
      <Button
        onClick={() => {
          setAsking(true);
        }}
        data-testid="sr-withdraw"
      >
        {t('requests.withdraw')}
      </Button>
      <Modal
        open={asking}
        title={t('requests.withdraw')}
        okText={t('requests.withdraw')}
        okButtonProps={{ danger: true, loading: pending }}
        cancelText={t('actions.cancel')}
        onOk={() => {
          onWithdraw();
          setAsking(false);
        }}
        onCancel={() => {
          setAsking(false);
        }}
      >
        {t('requests.withdraw_confirm')}
      </Modal>
    </>
  );
}
