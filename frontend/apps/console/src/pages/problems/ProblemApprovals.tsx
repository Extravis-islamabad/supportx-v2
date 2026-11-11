import { CloseOutlined } from '@ant-design/icons';
import { Button, Flex, Form, List, Modal, Radio, Typography } from 'antd';
import { useState } from 'react';

import {
  useDecideProblemApproval,
  useProblemApprovals,
  useRequestProblemApproval,
  type Problem,
  type ProblemApprovalPurpose,
} from '@supportx/api-client';
import {
  EmptyText,
  FormProblem,
  ToneTag,
  WriteButton,
  reportError,
  useDateTime,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

import { UserPicker } from '../incidents/pickers';
import { DecisionDialog } from '../requests/DecisionDialog';

type Tone = 'info' | 'success' | 'warning' | 'error';
const TONE: Record<string, Tone> = {
  pending: 'warning',
  approved: 'success',
  rejected: 'error',
  withdrawn: 'info',
  not_needed: 'info',
};

/**
 * A problem's approvals (WP-044b s4): each approver's entry and decision, with Approve and
 * Reject for the named approver (the requests' decision dialog: a rejection gives its reason).
 * A decision never moves the problem; an approved acceptance shows on the record.
 */
export function ProblemApprovals({ item }: { item: Problem }) {
  const t = useLabel();
  const { format } = useDateTime();
  const approvals = useProblemApprovals(item.id);
  const decide = useDecideProblemApproval(item.id);
  const [deciding, setDeciding] = useState<{
    id: string;
    version: number;
    decision: 'approve' | 'reject';
    commentsRequired: boolean;
  }>();
  const problems: string[] = [];
  const people = approvals.data?.people ?? {};
  const rows = approvals.data?.items ?? [];
  return (
    <Flex vertical gap={8} data-testid="prb-approvals">
      {item.accepted_at != null && (
        <Typography.Text type="secondary" data-testid="prb-accepted">
          {t('problems.approvals.accepted', {
            date: format(item.accepted_at),
            review: format(item.accept_review_at),
          })}
        </Typography.Text>
      )}
      {/* Start-aligned as the panel's other empty texts, not a list's centred one (QA10V-18). */}
      {rows.length === 0 && <EmptyText>{t('problems.approvals.none')}</EmptyText>}
      <List
        size="small"
        dataSource={rows}
        locale={{ emptyText: <span /> }}
        style={rows.length === 0 ? { display: 'none' } : undefined}
        renderItem={(a) => (
          <List.Item
            key={a.id}
            data-testid={`prb-approval-${a.id}`}
            actions={
              a.can_decide
                ? (['approve', 'reject'] as const).map((d) => (
                    <WriteButton
                      key={d}
                      size="small"
                      danger={d === 'reject'}
                      disabled={decide.isPending}
                      data-testid={`prb-approval-${a.id}-${d}`}
                      onClick={() => {
                        setDeciding({
                          id: a.id,
                          version: a.version,
                          decision: d,
                          commentsRequired: a.comments_required,
                        });
                      }}
                    >
                      {t(d === 'approve' ? 'requests.approve' : 'requests.reject')}
                    </WriteButton>
                  ))
                : []
            }
          >
            <Flex gap={8} wrap align="center">
              <bdi dir="auto">
                {a.approver_id == null ? '' : (people[a.approver_id]?.display_name ?? '')}
              </bdi>
              <ToneTag tone={TONE[a.state] ?? 'info'}>{t(`approval_state.${a.state}`)}</ToneTag>
              {a.decided_at != null && (
                <Typography.Text type="secondary">{format(a.decided_at)}</Typography.Text>
              )}
              {a.comment != null && <bdi dir="auto">{a.comment}</bdi>}
            </Flex>
          </List.Item>
        )}
      />
      {deciding && (
        <DecisionDialog
          decision={deciding.decision}
          commentsRequired={deciding.commentsRequired}
          pending={decide.isPending}
          problems={problems}
          onClose={() => {
            setDeciding(undefined);
          }}
          onSend={(comment, isPrivate) => {
            decide.mutate(
              {
                approvalId: deciding.id,
                version: deciding.version,
                decision: deciding.decision,
                comment,
                isPrivate,
              },
              {
                onSuccess: () => {
                  setDeciding(undefined);
                },
                onError: reportError,
              },
            );
          }}
        />
      )}
    </Flex>
  );
}

/** "Ask for approval": named people, for the problem itself or to accept it without a fix. */
export function RequestApprovalDialog({
  item,
  open,
  onClose,
}: {
  item: Problem;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const ask = useRequestProblemApproval(item.id);
  const problem = useFormProblem();
  const [people, setPeople] = useState<string[]>([]);
  const knownError = item.known_error_at != null && item.known_error_retired_at == null;
  const [purpose, setPurpose] = useState<ProblemApprovalPurpose>('record');
  const close = () => {
    setPeople([]);
    setPurpose('record');
    problem.clear();
    onClose();
  };
  return (
    <Modal
      open={open}
      title={t('problems.approvals.ask')}
      okText={t('problems.approvals.send')}
      okButtonProps={{ disabled: people.length === 0, loading: ask.isPending }}
      onOk={() => {
        ask.mutate(
          { approverIds: people, purpose, version: item.version },
          { onSuccess: close, onError: (error) => problem.show(error) },
        );
      }}
      onCancel={close}
      destroyOnHidden
    >
      <Form layout="vertical" data-testid="prb-approval-dialog">
        {knownError && (
          <Form.Item label={t('problems.approvals.purpose')}>
            <Radio.Group
              value={purpose}
              onChange={(e) => {
                setPurpose(e.target.value as ProblemApprovalPurpose);
              }}
              options={(['record', 'accept_without_fix'] as const).map((p) => ({
                value: p,
                label: t(`approval_purpose.${p}`),
              }))}
            />
          </Form.Item>
        )}
        <Form.Item label={t('problems.approvals.approvers')} required>
          <Flex vertical gap={8}>
            {people.map((id) => (
              <Flex key={id} gap={8} align="center">
                <UserPicker
                  id={`prb-approver-${id}`}
                  value={id}
                  onChange={() => undefined}
                  disabled
                  testId={`prb-approver-${id}`}
                  ariaLabel={t('problems.approvals.approvers')}
                />
                <Button
                  type="text"
                  size="small"
                  icon={<CloseOutlined />}
                  aria-label={t('problems.approvals.remove')}
                  onClick={() => {
                    setPeople(people.filter((p) => p !== id));
                  }}
                />
              </Flex>
            ))}
            <UserPicker
              id="prb-approver-add"
              value={null}
              onChange={(id) => {
                if (id !== null && !people.includes(id)) setPeople([...people, id]);
              }}
              testId="prb-approver-add"
              ariaLabel={t('problems.approvals.add')}
            />
          </Flex>
        </Form.Item>
        <FormProblem problem={problem} />
      </Form>
    </Modal>
  );
}
