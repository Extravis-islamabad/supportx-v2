import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import type { IncidentCatalogue, IncidentCategory } from './incidents';
import { queryKeys } from './keys';
import type { components } from './schema';

// Incident settings screens and templates (WP-020c). Every settings write sends If-Match with
// the catalogue version the screen showed and answers with the new catalogue, which replaces
// the cached one at once; other screens follow through `work_items.settings_changed`.
export type IncidentTemplate = components['schemas']['TemplateOut'];
export type IncidentTemplateInput = components['schemas']['TemplateIn'];
export type IncidentTemplatePatch = components['schemas']['TemplatePatch'];
export type TemplateField = components['schemas']['TemplateField'];
export type FieldRule = components['schemas']['FieldRuleIO'];
export type PickList = components['schemas']['PickList'];
export type ListValue = components['schemas']['WorkItemListValueOut'];
export type IncidentScale = components['schemas']['Scale'];
export type ReasonMode = components['schemas']['ReasonMode'];
export type Labels = Record<string, string>;
type MatrixCell = components['schemas']['MatrixCellIn'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** Every template, the default first; disabled ones are included (they name old records). */
export function useIncidentTemplates(enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.templates,
    queryFn: () => call(api.GET('/api/v1/incidents/templates')),
    enabled,
    staleTime: 60_000,
  });
}

/** One settings change; `version` is the catalogue version the screen was showing. */
export type SettingsChange =
  | {
      kind: 'settings';
      body: Partial<components['schemas']['WorkItemSettingsPatch']>;
    }
  | { kind: 'status'; code: string; body: components['schemas']['StatusPatch'] }
  | { kind: 'transition'; from: string; action: string; reasonMode: ReasonMode }
  | {
      kind: 'scale';
      scale: IncidentScale;
      code: string;
      body: components['schemas']['ScaleValuePatch'];
    }
  | { kind: 'matrix'; cells: MatrixCell[] }
  | { kind: 'add_value'; list: PickList; labels: Labels; colour?: string | null }
  | { kind: 'value'; list: PickList; code: string; body: components['schemas']['ListValuePatch'] }
  | { kind: 'order'; list: PickList; codes: string[] };

function send(change: SettingsChange, version: number): Promise<IncidentCatalogue> {
  const header = ifMatch(version);
  switch (change.kind) {
    case 'settings':
      return call(
        api.PATCH('/api/v1/incidents/settings', { params: { header }, body: change.body }),
      );
    case 'status':
      return call(
        api.PATCH('/api/v1/incidents/settings/statuses/{code}', {
          params: { header, path: { code: change.code } },
          body: change.body,
        }),
      );
    case 'transition':
      return call(
        api.PATCH('/api/v1/incidents/settings/transitions/{from_status}/{action}', {
          params: {
            header,
            path: {
              from_status: change.from,
              action: change.action as components['schemas']['WorkItemAction'],
            },
          },
          body: { reason_mode: change.reasonMode },
        }),
      );
    case 'scale':
      return call(
        api.PATCH('/api/v1/incidents/settings/scales/{scale}/{code}', {
          params: { header, path: { scale: change.scale, code: change.code } },
          body: change.body,
        }),
      );
    case 'matrix':
      return call(
        api.PUT('/api/v1/incidents/settings/matrix', {
          params: { header },
          body: { cells: change.cells },
        }),
      );
    case 'add_value':
      return call(
        api.POST('/api/v1/incidents/settings/lists/{list_name}/values', {
          params: { header, path: { list_name: change.list } },
          body: { labels: change.labels, colour: change.colour ?? null },
        }),
      );
    case 'value':
      return call(
        api.PATCH('/api/v1/incidents/settings/lists/{list_name}/values/{code}', {
          params: { header, path: { list_name: change.list, code: change.code } },
          body: change.body,
        }),
      );
    case 'order':
      return call(
        api.PUT('/api/v1/incidents/settings/lists/{list_name}/order', {
          params: { header, path: { list_name: change.list } },
          body: { codes: change.codes },
        }),
      );
  }
}

// Catalogue versions this tab's own saves produced (QA BUG-02): a screen holding unsaved
// edits must not call those "changed elsewhere".
const ownVersions = new Set<number>();

/** Whether this tab's own save produced catalogue `version`. */
export function isOwnSettingsVersion(version: number): boolean {
  return ownVersions.has(version);
}

/**
 * Change the incident configuration (settings.manage). Each call uses the version of the cached
 * catalogue unless the caller passes one, so two quick edits in a row do not collide.
 */
export function useIncidentSettingsChange() {
  const queryClient = useQueryClient();
  return useMutation({
    // Screens show field errors next to the value; anything else goes through reportError.
    meta: { silent: true },
    mutationFn: ({ change, version }: { change: SettingsChange; version?: number }) => {
      const cached = queryClient.getQueryData<IncidentCatalogue>(queryKeys.incidents.catalogue);
      return send(change, version ?? cached?.version ?? 0);
    },
    onSuccess: (catalogue) => {
      ownVersions.add(catalogue.version);
      queryClient.setQueryData(queryKeys.incidents.catalogue, catalogue);
    },
    onError: () => {
      // A conflict or refusal: show what is saved now.
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.catalogue });
    },
  });
}

export type TemplateChange =
  | { kind: 'create'; body: IncidentTemplateInput }
  | { kind: 'update'; id: string; version: number; body: IncidentTemplatePatch }
  | { kind: 'copy'; id: string; labels: Labels };

/** Add, change or copy a template (settings.manage); the list refetches afterwards. */
export function useIncidentTemplateChange() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (change: TemplateChange): Promise<IncidentTemplate> => {
      if (change.kind === 'create') {
        return call(api.POST('/api/v1/incidents/templates', { body: change.body }));
      }
      if (change.kind === 'copy') {
        return call(
          api.POST('/api/v1/incidents/templates/{template_id}/copy', {
            params: { path: { template_id: change.id } },
            body: { labels: change.labels },
          }),
        );
      }
      return call(
        api.PATCH('/api/v1/incidents/templates/{template_id}', {
          params: { path: { template_id: change.id }, header: ifMatch(change.version) },
          body: change.body,
        }),
      );
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.templates });
    },
  });
}

export type CategoryChange =
  | {
      kind: 'create';
      parentId: string | null;
      labels: Labels;
      defaultGroupId?: string | null;
    }
  | {
      kind: 'update';
      id: string;
      version: number;
      body: components['schemas']['WorkItemCategoryPatch'];
    };

/** Add or change a category node (settings.manage); the tree refetches afterwards. */
export function useIncidentCategoryChange() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (change: CategoryChange): Promise<IncidentCategory> => {
      if (change.kind === 'create') {
        return call(
          api.POST('/api/v1/incidents/categories', {
            body: {
              parent_id: change.parentId,
              labels: change.labels,
              default_group_id: change.defaultGroupId ?? null,
            },
          }),
        );
      }
      return call(
        api.PATCH('/api/v1/incidents/categories/{category_id}', {
          params: { path: { category_id: change.id }, header: ifMatch(change.version) },
          body: change.body,
        }),
      );
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.categories });
    },
  });
}
