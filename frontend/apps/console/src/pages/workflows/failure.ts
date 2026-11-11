import type { useLabel } from '@supportx/ui';

type Translate = ReturnType<typeof useLabel>;

/**
 * Why a run stopped, in words (REQ-WF-024): the failure's own label, else the shared error or
 * problem label, else "This step failed". A raw code never reaches the screen (rule d).
 */
export function failureText(t: Translate, code: string, params: Record<string, unknown> = {}) {
  const values = Object.fromEntries(
    Object.entries(params).map(([k, v]) => [k, typeof v === 'number' ? v : String(v)]),
  );
  for (const key of [`workflow_failure.${code}`, `errors.${code}`, `workflow_problem.${code}`]) {
    const shown = t(key, values);
    if (shown !== key) return shown;
  }
  return t('workflow_failure.unknown');
}

// Why a run was stopped: a code the platform set (the record was canceled), or the words of the
// person who stopped it (REQ-WF-026 AC1), shown as typed.
const STOP_CODES = new Set(['record_canceled']);

export function stoppedText(t: Translate, reason: string): string {
  return STOP_CODES.has(reason) ? t(`workflow_failure.${reason}`) : reason;
}
