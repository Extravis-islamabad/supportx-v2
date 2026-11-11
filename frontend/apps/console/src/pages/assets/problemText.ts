import { ApiError } from '@supportx/api-client';
import type { LabelParams } from '@supportx/labels';
import { reportError, type useLabel } from '@supportx/ui';

type T = ReturnType<typeof useLabel>;

/**
 * A refusal as words: the field's own message where the API names one, else the problem's
 * (never a code). `params` rewrites a problem's parameters before they are shown (a date the
 * API sends as ISO, shown in the person's format). Anything else is reported, and null returned.
 */
export function problemText(
  t: T,
  error: unknown,
  params?: (code: string, given: LabelParams) => LabelParams,
): string | null {
  if (error instanceof ApiError && error.problem !== null) {
    const field = error.fieldErrors[0];
    if (field !== undefined) return t(`errors.field.${field.code}`, field.params ?? {});
    const given = error.params as LabelParams;
    return t(error.messageKey, params === undefined ? given : params(error.code, given));
  }
  reportError(error);
  return null;
}
