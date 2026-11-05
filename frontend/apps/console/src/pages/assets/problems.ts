import { useState } from 'react';

import { reportError, useLabel } from '@supportx/ui';

import { fieldMessages, refusalMessages } from '../admin/incidents/helpers';

/**
 * A save's refusals for the form that made it (field problems, a full plan, a taken tag), shown
 * once there; a conflict or an outage is reported as everywhere else.
 */
export function useAssetSaveProblems() {
  const t = useLabel();
  const [problems, setProblems] = useState<string[]>([]);
  return {
    problems,
    show: (error: unknown) => {
      const shown = refusalMessages(t, error, fieldMessages(t, error));
      if (shown.length > 0) setProblems(shown);
      else reportError(error);
    },
    clear: () => {
      setProblems([]);
    },
  };
}
