import type { ReleaseTemplate } from '@supportx/api-client';

import { labelled } from '../incidents/labels';

type Translate = (key: string, params?: Record<string, string | number>) => string;

// The staged types' shared names (moved next to the shared move dialog, lane C's review of #372).
export { listValueName, stageName, statusName } from '../staged/labels';

export function templateName(t: Translate, locale: string, template: ReleaseTemplate): string {
  return labelled(template.labels, locale, () => t(`release_template.${template.code ?? ''}`));
}

/** The emergency path is the release's emergency flag (REQ-REL-012 AC3). */
export const EMERGENCY_PATH = 'emergency';
