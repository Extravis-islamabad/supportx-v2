import { Tooltip } from 'antd';

import type { IncidentActionState } from '@supportx/api-client';
import { WriteButton } from '@supportx/ui';

import { useActionReason } from './actionReason';

/** An operation in its fixed place; disabled ones say why (REQ-WI-010). */
export function OperationButton({
  state,
  label,
  testId,
  onClick,
  loading,
}: {
  state: IncidentActionState | undefined;
  label: string;
  testId: string;
  onClick: () => void;
  loading?: boolean;
}) {
  const reasonText = useActionReason();
  if (state === undefined) return null;
  const button = (
    <WriteButton disabled={!state.allowed} onClick={onClick} loading={loading} data-testid={testId}>
      {label}
    </WriteButton>
  );
  if (state.allowed || state.reason == null) return button;
  return (
    <Tooltip title={reasonText(state)}>
      <span data-testid={`${testId}-reason`} data-reason={state.reason}>
        {button}
      </span>
    </Tooltip>
  );
}
