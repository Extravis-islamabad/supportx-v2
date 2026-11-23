import { Alert, Form, Input, Modal, Select, Space, Tag } from 'antd';
import { useState } from 'react';

import { useUser, type Approval, type ApproverChange } from '@supportx/api-client';
import { lengthLimit, useLabel } from '@supportx/ui';

import { shownName, useHiddenPersonLabel } from '../../maskedPeople';
import { UserPicker } from '../incidents/pickers';

// The dialog of one adjustment of a request's running approval (WP-047a S2b, REQ-SR-042).

const REASON_MAX = 500;

export type Asking =
  | { kind: 'add'; stages: number[] }
  | { kind: 'replace'; approval: Approval }
  | { kind: 'stage' }
  | { kind: 'remind' };

export function ChangeDialog({
  asking,
  pending,
  onClose,
  onSend,
}: {
  asking: Asking;
  pending: boolean;
  onClose: () => void;
  onSend: (body: ApproverChange, onProblems: (messages: string[]) => void) => void;
}) {
  const t = useLabel();
  const [reason, setReason] = useState('');
  const [person, setPerson] = useState<string | null>(null);
  const [people, setPeople] = useState<string[]>([]);
  const [rule, setRule] = useState<'any' | 'all' | 'majority'>('any');
  const [stage, setStage] = useState(asking.kind === 'add' ? (asking.stages[0] ?? 1) : 1);
  const [problems, setProblems] = useState<string[]>([]);
  const needsPerson = asking.kind === 'add' || asking.kind === 'replace';
  const ready =
    reason.trim() !== '' &&
    (!needsPerson || person !== null) &&
    (asking.kind !== 'stage' || people.length > 0);
  const submit = () => {
    const why = reason.trim();
    const body: ApproverChange =
      asking.kind === 'add'
        ? { kind: 'add', stage, approverId: person ?? '', reason: why }
        : asking.kind === 'replace'
          ? {
              kind: 'replace',
              approvalId: asking.approval.id,
              approverId: person ?? '',
              reason: why,
            }
          : asking.kind === 'stage'
            ? { kind: 'stage', approverIds: people, rule, reason: why }
            : { kind: 'remind', reason: why };
    onSend(body, setProblems);
  };
  return (
    <Modal
      open
      title={t(
        `requests.approvers.${asking.kind === 'add' ? 'add' : asking.kind === 'stage' ? 'add_stage' : asking.kind}`,
      )}
      okText={t('actions.save')}
      okButtonProps={{ disabled: !ready, loading: pending, 'data-testid': 'approvers-send' }}
      cancelText={t('actions.cancel')}
      onOk={submit}
      onCancel={onClose}
    >
      <Form layout="vertical">
        {asking.kind === 'add' && asking.stages.length > 1 && (
          <Form.Item label={t('requests.approvers.stage')}>
            <Select
              value={stage}
              onChange={setStage}
              options={asking.stages.map((n) => ({
                value: n,
                label: t('requests.stage_n', { n }),
              }))}
              data-testid="approvers-stage"
            />
          </Form.Item>
        )}
        {needsPerson && (
          <Form.Item label={t('requests.approvers.person')} required>
            <UserPicker
              value={person}
              onChange={setPerson}
              testId="approvers-person"
              ariaLabel={t('requests.approvers.person')}
            />
          </Form.Item>
        )}
        {asking.kind === 'stage' && (
          <>
            <Form.Item label={t('requests.approvers.people')} required>
              <Space direction="vertical" style={{ width: '100%' }}>
                <UserPicker
                  value={null}
                  onChange={(id) => {
                    if (id !== null && !people.includes(id)) setPeople([...people, id]);
                  }}
                  testId="approvers-people"
                  ariaLabel={t('requests.approvers.people')}
                />
                <Space wrap>
                  {people.map((id) => (
                    <PersonTag
                      key={id}
                      id={id}
                      onRemove={() => {
                        setPeople(people.filter((p) => p !== id));
                      }}
                    />
                  ))}
                </Space>
              </Space>
            </Form.Item>
            <Form.Item label={t('requests.approvers.rule')}>
              <Select
                value={rule}
                onChange={setRule}
                options={(['any', 'all', 'majority'] as const).map((r) => ({
                  value: r,
                  label: t(`approval_rule.${r}`),
                }))}
                data-testid="approvers-rule"
              />
            </Form.Item>
          </>
        )}
        {asking.kind === 'replace' && (
          <Alert type="info" showIcon message={t('requests.approvers.replace_note')} />
        )}
        <Form.Item label={t('requests.approvers.reason')} required>
          <Input.TextArea
            value={reason}
            count={lengthLimit(REASON_MAX)}
            onChange={(e) => {
              setReason(e.target.value);
            }}
            data-testid="approvers-reason"
          />
        </Form.Item>
        {problems.length > 0 && (
          <Alert
            type="error"
            showIcon
            message={problems.join(' ')}
            data-testid="approvers-problems"
          />
        )}
      </Form>
    </Modal>
  );
}

/** A chosen person by name (or the masked stand-in), never the ID (rule 5d). */
function PersonTag({ id, onRemove }: { id: string; onRemove: () => void }) {
  const t = useLabel();
  const hidden = useHiddenPersonLabel();
  const person = useUser(id, { silent: true });
  const name = person.isLoading
    ? t('shell.loading')
    : person.isError
      ? t('incidents.person_unseen')
      : shownName(person.data?.display_name, hidden);
  return (
    <Tag closable onClose={onRemove} data-testid="approvers-chosen">
      <bdi>{name}</bdi>
    </Tag>
  );
}
