import type { FormInstance } from 'antd';

import { ApiError } from '@supportx/api-client';
import { formFieldOf } from '@supportx/forms';
import { markHandled } from '@supportx/ui';

/**
 * Server field errors (RFC 9457 `errors[]`) under the matching Ant Design fields; `names` maps an
 * API field to a form field when they differ (`names.en` → `name_en`). True when any was shown,
 * so the caller does not also report the error as a toast.
 */
export function showFieldErrors(
  form: FormInstance,
  error: unknown,
  t: (key: string, params?: Record<string, string>) => string,
  names: Record<string, string> = {},
): boolean {
  if (!(error instanceof ApiError)) return false;
  const known = new Set(Object.keys(form.getFieldsValue(true) as Record<string, unknown>));
  const fields = error.fieldErrors
    .map((fieldError) => {
      const api = formFieldOf(fieldError.field);
      const name = names[api] ?? api;
      const params = Object.fromEntries(
        Object.entries(fieldError.params ?? {}).map(([k, v]) => [k, String(v)]),
      );
      return { name, errors: [t(fieldError.message_key, params)] };
    })
    .filter((field) => known.has(field.name));
  if (fields.length === 0) return false;
  form.setFields(fields);
  markHandled(error);
  return true;
}
