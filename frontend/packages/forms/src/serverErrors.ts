import type { FieldValues, Path, UseFormSetError } from 'react-hook-form';

import { ApiError } from '@supportx/api-client';

/** `body.signature` → `signature`; `query.filter.and[0]` stays as is (not a form field). */
export function formFieldOf(apiField: string): string {
  return apiField.startsWith('body.') ? apiField.slice('body.'.length) : apiField;
}

/**
 * Put the API's field errors (RFC 9457 `errors[]`) under the matching form fields. The message
 * is a labels key (`errors.field.<code>`) plus params; <FormField> translates it.
 * Returns true when at least one error landed on a field, so the caller can skip the toast.
 */
export function applyServerErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  fields: readonly Path<T>[],
): boolean {
  if (!(error instanceof ApiError)) return false;
  let applied = false;
  for (const fieldError of error.fieldErrors) {
    const name = formFieldOf(fieldError.field);
    if ((fields as readonly string[]).includes(name)) {
      setError(name as Path<T>, {
        type: 'server',
        message: JSON.stringify({ key: fieldError.message_key, params: fieldError.params ?? {} }),
      });
      applied = true;
    }
  }
  return applied;
}

export interface FieldMessage {
  key: string;
  params: Record<string, unknown>;
}

/**
 * Field error messages are carried as labels keys: from the server as JSON {key, params}
 * (applyServerErrors), from Zod schemas as a bare key (`z.string().max(5, 'errors.field.x')`).
 */
export function parseFieldMessage(message: string | undefined): FieldMessage | null {
  if (message === undefined || message === '') return null;
  if (message.startsWith('{')) {
    try {
      return JSON.parse(message) as FieldMessage;
    } catch {
      return { key: 'errors.field.invalid_value', params: {} };
    }
  }
  return { key: message, params: {} };
}
