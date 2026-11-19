import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// Custom fields (WP-026, REQ-INC-014): definitions from the metadata module, values on each
// record as `custom` by key. Screens show a field's `labels`, never its key (AC3). Every
// change reaches open screens through `metadata.custom_fields_changed` (ConsoleLayout).
export type CustomField = components['schemas']['CustomFieldOut'];
export type CustomFieldInput = components['schemas']['CustomFieldIn'];
export type CustomFieldPatch = components['schemas']['CustomFieldPatch'];
export type CustomFieldType = components['schemas']['FieldType'];
export type CustomFieldEntity = components['schemas']['CustomFieldEntity'];
export type CustomFieldChoice = components['schemas']['CustomFieldChoiceIO'];
export type CustomFieldValidation = components['schemas']['CustomFieldValidationIO'];
export type CustomFieldIndexState = components['schemas']['IndexState'];

/** Optional extras of `useCustomFields` (0175). */
export interface CustomFieldsOptions {
  /** Only the fields records of this type have (the entity's, and its own and its parents'). */
  typeId?: string;
}

/**
 * The entity's fields in display order (retired ones included and marked). `removed` adds the
 * fields removed while in use, to name old values in history. `options.typeId` (0175): one
 * type's fields, each marked `inherited` when it is the entity's or a parent type's; the query
 * key gains the type only then, so every other call keeps its key.
 */
export function useCustomFields(
  entity: CustomFieldEntity,
  removed = false,
  enabled = true,
  options?: CustomFieldsOptions,
) {
  const typeId = options?.typeId;
  return useQuery({
    queryKey:
      typeId === undefined
        ? queryKeys.customFields.list(entity, removed)
        : queryKeys.customFields.forType(entity, removed, typeId),
    queryFn: () =>
      call(
        api.GET('/api/v1/custom-fields', {
          params: {
            query:
              typeId === undefined
                ? { entity, include_removed: removed }
                : { entity, include_removed: removed, type_id: typeId },
          },
        }),
      ),
    enabled,
    staleTime: 60_000,
  });
}

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

export type CustomFieldChange =
  | { kind: 'create'; body: CustomFieldInput }
  | { kind: 'update'; id: string; version: number; body: CustomFieldPatch }
  | { kind: 'delete'; id: string; version: number; confirm: boolean }
  | { kind: 'order'; entity: CustomFieldEntity; ids: string[] }
  | { kind: 'index'; id: string; version: number };

function send(change: CustomFieldChange): Promise<unknown> {
  switch (change.kind) {
    case 'create':
      return call(api.POST('/api/v1/custom-fields', { body: change.body }));
    case 'update':
      return call(
        api.PATCH('/api/v1/custom-fields/{field_id}', {
          params: { path: { field_id: change.id }, header: ifMatch(change.version) },
          body: change.body,
        }),
      );
    case 'delete':
      return call(
        api.DELETE('/api/v1/custom-fields/{field_id}', {
          params: {
            path: { field_id: change.id },
            header: ifMatch(change.version),
            query: { confirm: change.confirm },
          },
        }),
      );
    case 'order':
      return call(
        api.PUT('/api/v1/custom-fields/order', {
          body: { entity: change.entity, ids: change.ids },
        }),
      );
    case 'index':
      return call(
        api.POST('/api/v1/custom-fields/{field_id}/index', {
          params: { path: { field_id: change.id }, header: ifMatch(change.version) },
        }),
      );
  }
}

/** Add, change, reorder, remove or index a field (settings.manage); lists refetch after. */
export function useCustomFieldChange() {
  const queryClient = useQueryClient();
  return useMutation({
    // Screens show field errors next to the value; anything else goes through reportError.
    meta: { silent: true },
    mutationFn: send,
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.customFields.all });
    },
  });
}
