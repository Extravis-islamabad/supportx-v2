import type { ChangeBoard, ChangeTemplate } from '@supportx/api-client';

import { labelled } from '../incidents/labels';

type Translate = (key: string, params?: Record<string, string | number>) => string;

export function templateName(t: Translate, locale: string, template: ChangeTemplate): string {
  return labelled(template.labels, locale, () => t(`change_template.${template.code ?? ''}`));
}

/** The emergency path (REQ-CHG-005): flagged on the list and the record. */
export const EMERGENCY_PATH = 'emergency';

/** Risk levels lowest first (REQ-CHG-056), and the tone each shows with. */
export const RISKS = ['low', 'medium', 'high', 'very_high'] as const;
export const riskTone = (risk: string): 'error' | 'warning' | 'default' =>
  risk === 'high' || risk === 'very_high' ? 'error' : risk === 'medium' ? 'warning' : 'default';

/** A board by its seeded code, its own labels, or the name an admin gave it. */
export function boardName(t: Translate, locale: string, board: ChangeBoard): string {
  return labelled(board.labels, locale, () =>
    board.code ? t(`change_board.${board.code}`) : board.name,
  );
}
