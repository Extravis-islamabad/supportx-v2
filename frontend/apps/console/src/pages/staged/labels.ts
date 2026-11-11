import { labelled } from '../incidents/labels';

// Names of the staged types' codes (releases and changes, ADR-041), next to their shared move
// dialog (lane C's review of #372). The release pages re-export them from ../releases/labels.
type Translate = (key: string, params?: Record<string, string | number>) => string;
interface ListValue {
  code: string;
  labels?: Record<string, string> | null;
}

/** A stage by its code (the labels package; ADR-041 keeps stage codes stable). */
export const stageName = (t: Translate, code: string | null | undefined): string =>
  code ? t(`work_item_stage.${code}`) : '';

/** A status by its code: staged statuses carry their stage in the code, labels give the name. */
export const statusName = (t: Translate, code: string | null | undefined): string =>
  code ? t(`work_item_status.${code}`) : '';

/** A value of one of the type's own lists (types, reasons, downtime kinds). */
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
