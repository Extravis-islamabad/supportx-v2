import { Select } from 'antd';

import { useVersionSteps } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

import { useStepName } from '../../workflows/stepName';

const NONE: readonly { id: string; type: string }[] = [];

/**
 * The runs' step filter: a step of the chosen workflow's published version, by name (QA
 * 2026-11-11 F-07). Without a workflow there is nothing to choose from, and it says so.
 */
export function StepPick({
  workflowId,
  version,
  value,
  onChange,
}: {
  workflowId: string | undefined;
  version: number | undefined;
  value: string | undefined;
  onChange: (node: string | undefined) => void;
}) {
  const t = useLabel();
  const steps = useVersionSteps(workflowId ?? '', version);
  const name = useStepName(steps.data ?? NONE);
  return (
    <Select<string>
      id="runs-node"
      allowClear
      disabled={workflowId === undefined}
      placeholder={workflowId === undefined ? t('workflows.runs.step_choose_workflow') : undefined}
      value={value}
      // Cleared: antd passes undefined at run time although its type says string.
      onChange={(node: string | undefined) => {
        onChange(node);
      }}
      options={(steps.data ?? []).map((s) => ({ value: s.id, label: name(s.id) }))}
      data-testid="runs-node"
    />
  );
}
