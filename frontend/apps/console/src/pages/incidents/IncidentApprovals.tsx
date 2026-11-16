import { CloseOutlined } from '@ant-design/icons';
import { Button, Flex, Form, List, Modal, Radio, Typography } from 'antd';
import { useState } from 'react';

import {
  useDecideIncidentApproval,
  useIncidentApprovals,
  useRequestIncidentApproval,
  type Incident,
  type IncidentApprovalRule,
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

import { DecisionDialog } from '../requests/DecisionDialog';
import { UserPicker } from './pickers';

type Tone = 'info' | 'success' | 'warning' | 'error';
const TONE: Record<string, Tone> = {
  pending: 'warning',
  approved: 'success',
  rejected: 'error',
  withdrawn: 'info',
  not_needed: 'info',
};
const RULES: readonly IncidentApprovalRule[] = ['any', 'all', 'majority'];

/**
 * An incident's approvals (WP-046b S1, REQ-INC-083): each approver, live, with Approve and
 * Reject for the named approver (the requests' decision dialog: a rejection gives its reason).
 * The incident's rule decides; a decision never moves its status.
 */
export function IncidentApprovals({ item }: { item: Incident }) {
  const t = useLabel();
  const { format } = useDateTime();
  const approvals = useIncidentApprovals(item.id);
  const decide = useDecideIncidentApproval(item.id);
  const [deciding, setDeciding] = useState<{
    id: string;
    version: number;
    decision: 'approve' | 'reject';
    commentsRequired: boolean;
  }>();
  const people = approvals.data?.people ?? {};
  const rows = approvals.data?.items ?? [];
  return (
    <Flex vertical gap={8} data-testid="inc-approvals">
      {rows.length === 0 && <EmptyText>{t('problems.approvals.none')}</EmptyText>}
      <List
        size="small"
        dataSource={rows}
        locale={{ emptyText: <span /> }}
        style={rows.length === 0 ? { display: 'none' } : undefined}
        renderItem={(a) => (
          <List.Item
            key={a.id}
            data-testid={`inc-approval-${a.id}`}
            actions={
              a.can_decide
                ? (['approve', 'reject'] as const).map((d) => (
                    <WriteButton
                      key={d}
                      size="small"
                      danger={d === 'reject'}
                      disabled={decide.isPending}
                      data-testid={`inc-approval-${a.id}-${d}`}
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
          problems={[]}
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

/** "Ask for approval": named people and how they decide (any one, all, a majority). */
export function AskApprovalDialog({
  item,
  open,
  onClose,
}: {
  item: Incident;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const ask = useRequestIncidentApproval(item.id);
  const problem = useFormProblem();
  const [people, setPeople] = useState<string[]>([]);
  const [rule, setRule] = useState<IncidentApprovalRule>('any');
  const close = () => {
    setPeople([]);
    setRule('any');
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
          { approverIds: people, rule, version: item.version },
          { onSuccess: close, onError: (error) => problem.show(error) },
        );
      }}
      onCancel={close}
      destroyOnHidden
    >
      <Form layout="vertical" data-testid="inc-approval-dialog">
        <Form.Item label={t('problems.approvals.approvers')} required>
          <Flex vertical gap={8}>
            {people.map((id) => (
              <Flex key={id} gap={8} align="center">
                <UserPicker
                  id={`inc-approver-${id}`}
                  value={id}
                  onChange={() => undefined}
                  disabled
                  testId={`inc-approver-${id}`}
                  ariaLabel={t('problems.approvals.approvers')}
                />
                <Button
                  type="text"
                  size="small"
                  icon={<CloseOutlined aria-hidden />}
                  aria-label={t('problems.approvals.remove')}
                  onClick={() => {
                    setPeople(people.filter((p) => p !== id));
                  }}
                />
              </Flex>
            ))}
            <UserPicker
              id="inc-approver-add"
              value={null}
              onChange={(id) => {
                if (id !== null && !people.includes(id)) setPeople([...people, id]);
              }}
              testId="inc-approver-add"
              ariaLabel={t('problems.approvals.add')}
            />
          </Flex>
        </Form.Item>
        {people.length > 1 && (
          <Form.Item label={t('incidents.approvals.rule')}>
            <Radio.Group
              value={rule}
              onChange={(e) => {
                setRule(e.target.value as IncidentApprovalRule);
              }}
              options={RULES.map((r) => ({ value: r, label: t(`approval_rule.${r}`) }))}
              data-testid="inc-approval-rule"
            />
          </Form.Item>
        )}
        <FormProblem problem={problem} />
      </Form>
    </Modal>
  );
}
