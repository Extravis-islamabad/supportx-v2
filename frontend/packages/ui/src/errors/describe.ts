import { ApiError } from '@supportx/api-client';
import type { LabelInput, LabelParams } from '@supportx/labels';

type Translate = (key: LabelInput, params?: LabelParams) => string;

export interface ErrorDescription {
  title: string;
  /** Extra explanation (feature name, licence reason), already translated. */
  detail?: string;
  /** Support reference (request ID), when there is one. */
  reference: string | null;
}

/**
 * The problem's params as label values. Every code gets them (a label's `{{placeholders}}` are
 * filled from the params the server sends, QA WP-029 BUG-01); nested values are left out.
 */
function labelParams(params: Record<string, unknown>): LabelParams {
  const values: LabelParams = {};
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      values[key] = value;
    }
  }
  return values;
}

/**
 * Turn any error into translated text. Never returns a code, JSON or stack trace (rule d): an
 * unknown error becomes the generic "something went wrong" message.
 */
export function describeError(error: unknown, t: Translate): ErrorDescription {
  if (!(error instanceof ApiError)) {
    return { title: t('errors.internal_error'), reference: null };
  }
  const reference = error.requestId;
  if (error.kind === 'network') {
    return { title: t('errors.network_error'), reference };
  }
  const params = error.params;
  const values = labelParams(params);
  switch (error.code) {
    case 'entitlement_required': {
      const feature = typeof params.feature === 'string' ? params.feature : null;
      return {
        title: t('errors.entitlement_required', values),
        detail:
          feature === null
            ? undefined
            : t('errors.entitlement_required.detail', { feature: t(`feature.${feature}`) }),
        reference,
      };
    }
    case 'read_only_mode': {
      const reason = typeof params.reason === 'string' ? params.reason : 'no_entitlement';
      return {
        title: t('errors.read_only_mode', values),
        detail: t(`entitlement_reason.${reason}`),
        reference,
      };
    }
    case 'cannot_publish':
    case 'permission_denied': {
      // Why exactly (WP-012): the four-eyes rule, a missing audience, an ended window …
      const reason = typeof params.reason === 'string' ? params.reason : null;
      return {
        title: t(error.messageKey, values),
        detail: reason === null ? undefined : t(`action_reason.${reason}`, values),
        reference,
      };
    }
    default:
      return { title: t(error.messageKey, values), reference };
  }
}
