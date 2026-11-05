import type { ReleaseTemplate } from '@supportx/api-client';

import { labelled } from '../incidents/labels';

type Translate = (key: string, params?: Record<string, string | number>) => string;
interface ListValue {
  code: string;
  labels?: Record<string, string> | null;
}

/** A stage by its code (the labels package; ADR-041 keeps stage codes stable). */
export const stageName = (t: Translate, code: string | null | undefined): string =>
  code ? t(`work_item_stage.${code}`) : '';

/** A status by its code: release statuses carry their stage in the code, labels give the name. */
export const statusName = (t: Translate, code: string | null | undefined): string =>
  code ? t(`work_item_status.${code}`) : '';

/** A value of one of the type's own lists (release types, reasons, downtime kinds). */
export function listValueName(
  t: Translate,
  locale: string,
  list: string,
  value: ListValue | undefined,
  code: string | null | undefined,
): string {
  if (!code) return '';
  return labelled(value?.labels, locale, () => t(`${list}.${code}`));
}

export function templateName(t: Translate, locale: string, template: ReleaseTemplate): string {
  return labelled(template.labels, locale, () => t(`release_template.${template.code ?? ''}`));
}

/** The emergency path is the release's emergency flag (REQ-REL-012 AC3). */
export const EMERGENCY_PATH = 'emergency';
