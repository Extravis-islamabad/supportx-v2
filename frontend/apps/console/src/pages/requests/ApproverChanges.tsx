import { Space } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useChangeApprovers,
  useServiceRequest,
  type Approval,
  type ApproverChange,
} from '@supportx/api-client';
import { reportError, useLabel, useLicence, WriteButton } from '@supportx/ui';

import { ChangeDialog, type Asking } from './ApproverChangeDialog';

// Adjusting a request's running approval (WP-047a S2b, REQ-SR-042): add an approver to an open
// stage, replace one still waiting, add a stage, or remind the approvers, each with a reason.
// Without the right (or once the approval is decided) the actions stay visible, disabled, with
// the server's reason (AC2); the server refuses them on its own anyway.

type Refused = 'no_permission' | 'out_of_scope' | 'approval_not_running' | null | undefined;

/** The dialog and the actions' state for one request. */
export function useApproverChanges(recordId: string, items: Approval[], refused: Refused) {
  const t = useLabel();
  const licence = useLicence();
  const record = useServiceRequest(recordId);
  const change = useChangeApprovers();
  const [asking, setAsking] = useState<Asking>();
  const why = refused == null ? undefined : t(`requests.modify_refused.${refused}`);
  const open = [...new Set(items.filter((a) => a.state === 'pending').map((a) => a.stage))];
  const close = () => {
    setAsking(undefined);
  };
  const send = (body: ApproverChange, onProblems: (messages: string[]) => void) => {
    const version = record.data?.version;
    if (version === undefined) return;
    change.mutate(
      { recordId, version, change: body },
      {
        onSuccess: close,
        onError: (error) => {
          if (error instanceof ApiError && error.status === 422) {
            onProblems(error.fieldErrors.map((f) => t(f.message_key, f.params ?? {})));
            return;
          }
          close();
          reportError(error);
        },
      },
    );
  };
  const toolbar =
    items.length === 0 ? null : (
      <Space wrap data-testid="approver-changes">
        <WriteButton
          disabled={why !== undefined || open.length === 0}
          whyDisabled={why ?? t('requests.modify_refused.approval_not_running')}
          onClick={() => {
            setAsking({ kind: 'add', stages: open });
          }}
          data-testid="approvers-add"
        >
          {t('requests.approvers.add')}
        </WriteButton>
        <WriteButton
          disabled={why !== undefined || !licence.has('catalog')}
          whyDisabled={why ?? t('why.professional_edition')}
          onClick={() => {
            setAsking({ kind: 'stage' });
          }}
          data-testid="approvers-add-stage"
        >
          {t('requests.approvers.add_stage')}
        </WriteButton>
        <WriteButton
          disabled={why !== undefined}
          whyDisabled={why}
          onClick={() => {
            setAsking({ kind: 'remind' });
          }}
          data-testid="approvers-remind"
        >
          {t('requests.approvers.remind')}
        </WriteButton>
      </Space>
    );
  /** The row's own action: replace a person whose approval still waits. */
  const replaceButton = (a: Approval) =>
    a.state !== 'pending' ? null : (
      <WriteButton
        key="replace"
        disabled={why !== undefined}
        whyDisabled={why}
        onClick={() => {
          setAsking({ kind: 'replace', approval: a });
        }}
        data-testid="approver-replace"
      >
        {t('requests.approvers.replace')}
      </WriteButton>
    );
  const dialog =
    asking === undefined ? null : (
      <ChangeDialog asking={asking} pending={change.isPending} onClose={close} onSend={send} />
    );
  return { toolbar, replaceButton, dialog };
}
