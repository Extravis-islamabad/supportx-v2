import { useVersionSteps } from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';

import { useStepName } from './stepName';

const NONE: readonly { id: string; type: string }[] = [];

/** One version's step names (a run in a list names its steps by the version it runs). */
export function StepNames({
  workflowId,
  version,
  ids,
}: {
  workflowId: string;
  version: number | null | undefined;
  ids: readonly string[];
}) {
  const steps = useVersionSteps(workflowId, version ?? undefined);
  const name = useStepName(steps.data ?? NONE);
  const list = useListFormat();
  if (steps.data === undefined) return null;
  return <>{list(ids.map((id) => name(id)))}</>;
}
