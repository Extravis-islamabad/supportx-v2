import { Alert, Flex, List, Space, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useChangeApprovalPreview,
  useChangeBoards,
  useChangesSinceApproval,
  useDecideStagedApproval,
  useStagedApprovals,
  type ReleaseApproval,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import {
  EmptyText,
  FormProblem,
  ToneTag,
  WriteButton,
  useAppearance,
  useDateTime,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

import { personName } from '../incidents/labels';
import { DecisionDialog } from '../requests/DecisionDialog';
import { stageName } from '../staged/labels';
import { boardName } from './labels';

const STATE_TONE = { approved: 'success', rejected: 'error', withdrawn: 'default' } as const;

/**
 * The CAB and approvals panel (WP-045b; REQ-CHG-039..053): each stage's approvals with the board
 * they came from and why (its mapping matched, or the default board), a member's optional vote
 * shown as advisory and never counted, and the fallback to the approval administrators said
 * plainly. Approve and reject carry the approval's own If-Match. Below, what changed since each
 * stage was approved, field by field, with what each change does (REQ-CHG-053).
 */
export function ApprovalsPart({ id }: { id: string }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { format } = useDateTime();
  const approvals = useStagedApprovals('changes', id);
  const boards = useChangeBoards();
  const since = useChangesSinceApproval(id);
  const decide = useDecideStagedApproval('changes');
  const problem = useFormProblem();
  const [deciding, setDeciding] = useState<{
    approval: ReleaseApproval;
    decision: 'approve' | 'reject';
  }>();
  const [fieldProblems, setFieldProblems] = useState<string[]>([]);
  const rows = approvals.data?.items ?? [];
  const people = approvals.data?.people ?? {};
  const board = (boardId: string | null | undefined) => {
    const found = (boards.data ?? []).find((b) => b.id === boardId);
    return found ? boardName(t, locale, found) : t('changes.approvals.a_board');
  };
  const close = () => {
    setDeciding(undefined);
    setFieldProblems([]);
  };
  const changed = (since.data ?? []).filter((s) => s.changes.length > 0);
  return (
    <Flex vertical gap={16} data-testid="change-approvals">
      <List
        dataSource={rows}
        locale={{ emptyText: <EmptyText>{t('staged.approvals.none')}</EmptyText> }}
        renderItem={(a) => (
          <List.Item
            key={a.id}
            data-testid={`approval-${a.id}`}
            actions={
              a.can_decide
                ? [
                    <WriteButton
                      key="approve"
                      size="small"
                      disabled={decide.isPending}
                      onClick={() => {
                        setFieldProblems([]);
                        setDeciding({ approval: a, decision: 'approve' });
                      }}
                      data-testid={`approval-${a.id}-approve`}
                    >
                      {t('requests.approve')}
                    </WriteButton>,
                    <WriteButton
                      key="reject"
                      size="small"
                      danger
                      disabled={decide.isPending}
                      onClick={() => {
                        setFieldProblems([]);
                        setDeciding({ approval: a, decision: 'reject' });
                      }}
                      data-testid={`approval-${a.id}-reject`}
                    >
                      {t('requests.reject')}
                    </WriteButton>,
                  ]
                : []
            }
          >
            <List.Item.Meta
              title={
                <Space wrap>
                  <span>{stageName(t, a.record_stage)}</span>
                  <span>{t('staged.approvals.level', { level: a.stage })}</span>
                  {a.rule && <ToneTag tone="info">{t(`approval_rule.${a.rule}`)}</ToneTag>}
                  {a.board_id && (
                    <span data-testid={`approval-${a.id}-board`}>
                      {a.board_reason
                        ? t(`board_choice.${a.board_reason}`, { board: board(a.board_id) })
                        : board(a.board_id)}
                    </span>
                  )}
                </Space>
              }
              description={
                <Space wrap>
                  <span>
                    {a.approver_id
                      ? personName(people, a.approver_id)
                      : t('changes.approvals.administrators')}
                  </span>
                  <ToneTag
                    tone={
                      a.state in STATE_TONE
                        ? STATE_TONE[a.state as keyof typeof STATE_TONE]
                        : 'default'
                    }
                  >
                    {t(`approval_state.${a.state}`)}
                  </ToneTag>
                  {a.advisory && (
                    <ToneTag tone="default" testId={`approval-${a.id}-advisory`}>
                      {t('changes.approvals.advisory')}
                    </ToneTag>
                  )}
                  {Boolean(a.route_reason) && (
                    <span>{t(`approval_route_reason.${a.route_reason ?? ''}`)}</span>
                  )}
                  {a.decided_at && <span>{format(a.decided_at)}</span>}
                  {a.comment && <Typography.Text type="secondary">{a.comment}</Typography.Text>}
                </Space>
              }
            />
          </List.Item>
        )}
      />
      {changed.length > 0 && (
        <Alert
          type="warning"
          showIcon
          data-testid="change-changes-since"
          message={t('changes.approvals.changed_since')}
          description={
            <Flex vertical gap={4}>
              {changed.map((s) =>
                s.changes.map((c) => (
                  <span key={`${s.stage}-${c.field}`} data-testid={`since-${s.stage}-${c.field}`}>
                    {t('changes.approvals.change_line', {
                      stage: stageName(t, s.stage),
                      field: t(`reapproval_field.${c.field.split('.')[0] ?? c.field}`),
                      effect: t(`reapproval_effect.${c.effect}`),
                    })}
                  </span>
                )),
              )}
            </Flex>
          }
        />
      )}
      {deciding && (
        <DecisionDialog
          decision={deciding.decision}
          commentsRequired={deciding.approval.comments_required}
          pending={decide.isPending}
          problems={fieldProblems}
          onClose={close}
          onSend={(comment, isPrivate) => {
            decide.mutate(
              {
                id,
                approvalId: deciding.approval.id,
                version: deciding.approval.version,
                decision: deciding.decision,
                comment,
                isPrivate,
              },
              {
                onSuccess: close,
                onError: (error) => {
                  if (error instanceof ApiError && error.status === 422) {
                    setFieldProblems(
                      error.fieldErrors.map((f) => t(f.message_key, f.params ?? {})),
                    );
                    return;
                  }
                  close();
                  problem.show(error);
                },
              },
            );
          }}
        />
      )}
      <FormProblem problem={problem} />
    </Flex>
  );
}

/**
 * Before a move that raises a stage's approval: who would approve, who is left out and why
 * (segregation of duties, REQ-CHG-039), and whether the approval administrators decide too.
 * Shown in the move dialog; it changes nothing.
 */
export function ApprovalPreview({ id, stage }: { id: string; stage: string }) {
  const t = useLabel();
  const list = useListFormat();
  const preview = useChangeApprovalPreview(id, stage, true);
  const p = preview.data;
  if (p === undefined || p === null) return null;
  const people = (ids: string[]) =>
    list(
      ids.map((u) => personName(p.people ?? {}, u)),
      'conjunction',
    );
  return (
    <Alert
      type={p.barred.length > 0 || p.fallback_reason ? 'warning' : 'info'}
      showIcon
      style={{ marginBottom: 16 }}
      data-testid="approval-preview"
      message={
        p.approver_ids.length > 0
          ? t('changes.approvals.preview_who', { people: people(p.approver_ids) })
          : t('changes.approvals.preview_nobody')
      }
      description={
        <Flex vertical gap={4}>
          {p.barred.map((b) => (
            <span key={b.user_id} data-testid={`preview-barred-${b.user_id}`}>
              {t('changes.approvals.preview_barred', {
                person: people([b.user_id]),
                reason: t(`approval_route_reason.${b.reason}`),
              })}
            </span>
          ))}
          {Boolean(p.fallback_reason) && (
            <span data-testid="preview-fallback">
              {t('changes.approvals.preview_fallback', {
                reason: t(`approval_route_reason.${p.fallback_reason ?? ''}`),
              })}
            </span>
          )}
        </Flex>
      }
    />
  );
}
