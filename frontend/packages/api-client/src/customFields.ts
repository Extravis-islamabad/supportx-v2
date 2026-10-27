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

/**
 * The entity's fields in display order (retired ones included and marked). `removed` adds the
 * fields removed while in use, to name old values in history.
 */
export function useCustomFields(entity: CustomFieldEntity, removed = false, enabled = true) {
  return useQuery({
    queryKey: queryKeys.customFields.list(entity, removed),
    queryFn: () =>
      call(
        api.GET('/api/v1/custom-fields', {
          params: { query: { entity, include_removed: removed } },
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
