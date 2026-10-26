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
  switch (error.code) {
    case 'entitlement_required': {
      const feature = typeof params.feature === 'string' ? params.feature : null;
      return {
        title: t('errors.entitlement_required'),
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
        title: t('errors.read_only_mode'),
        detail: t(`entitlement_reason.${reason}`),
        reference,
      };
    }
    case 'cannot_publish':
    case 'permission_denied': {
      // Why exactly (WP-012): the four-eyes rule, a missing audience, an ended window …
      const reason = typeof params.reason === 'string' ? params.reason : null;
      return {
        title: t(error.messageKey),
        detail: reason === null ? undefined : t(`action_reason.${reason}`),
        reference,
      };
    }
    // Files (WP-022): the limits and the refused type are part of the message (AC2).
    case 'file_too_large':
    case 'file_type_blocked':
    case 'storage_quota_exceeded': {
      const values: Record<string, string | number> = {};
      for (const [key, value] of Object.entries(params)) {
        if (typeof value === 'string' || typeof value === 'number') values[key] = value;
      }
      return { title: t(error.messageKey, values), reference };
    }
    default:
      return { title: t(error.messageKey), reference };
  }
}
