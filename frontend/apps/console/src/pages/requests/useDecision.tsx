import { useState } from 'react';

import { ApiError, useDecideApproval, type ApprovalDecision } from '@supportx/api-client';
import { reportError, useLabel } from '@supportx/ui';

import { DecisionDialog } from './DecisionDialog';

// Deciding an approval (WP-030 s2), shared by the request page and the header drawer.
/** Decide one approval: the dialog, the call with If-Match, problems shown at the field. */
export function useDecision(recordId: string) {
  const t = useLabel();
  const decide = useDecideApproval();
  const [open, setOpen] = useState<{
    approval: { id: string; version: number; comments_required: boolean };
    decision: ApprovalDecision['decision'];
  }>();
  const [problems, setProblems] = useState<string[]>([]);
  const dialog =
    open === undefined ? null : (
      <DecisionDialog
        decision={open.decision}
        commentsRequired={open.approval.comments_required}
        pending={decide.isPending}
        problems={problems}
        onClose={() => {
          setOpen(undefined);
          setProblems([]);
        }}
        onSend={(comment, isPrivate) => {
          decide.mutate(
            {
              recordId,
              approvalId: open.approval.id,
              version: open.approval.version,
              body: { decision: open.decision, comment: comment || null, private: isPrivate },
            },
            {
              onSuccess: () => {
                setOpen(undefined);
                setProblems([]);
              },
              onError: (error) => {
                if (error instanceof ApiError && error.status === 422) {
                  setProblems(error.fieldErrors.map((f) => t(f.message_key, f.params ?? {})));
                  return;
                }
                setOpen(undefined);
                reportError(error);
              },
            },
          );
        }}
      />
    );
  return {
    dialog,
    start: (
      approval: { id: string; version: number; comments_required: boolean },
      decision: ApprovalDecision['decision'],
    ) => {
      setProblems([]);
      setOpen({ approval, decision });
    },
  };
}
