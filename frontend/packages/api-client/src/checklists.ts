import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import type { components } from './schema';

// WP-046a S2: a record's checklists (REQ-INC-040), the checklist library with its CSV import,
// and personal reminders (REQ-INC-082). Incidents, problems and changes share the engine routes,
// so the incident paths' types describe them all; only the prefix changes (as incidentParts).

export type ChecklistBase = 'incidents' | 'problems' | 'changes';
export type Checklist = components['schemas']['ChecklistOut'];
export type ChecklistItem = components['schemas']['ChecklistItemOut'];
export type ChecklistLibraryEntry = components['schemas']['LibraryOut'];
export type ChecklistImport = components['schemas']['ChecklistImportOut'];
export type Reminder = components['schemas']['ReminderOut'];
export type MyReminder = components['schemas']['MyReminderOut'];

function at<P extends string>(base: ChecklistBase, path: P): P {
  return path.replace('/api/v1/incidents/', `/api/v1/${base}/`) as P;
}

function ifMatch(version: number) {
  return { 'If-Match': `"${String(version)}"` };
}

export const checklistKeys = {
  of: (base: ChecklistBase, id: string) => ['checklists', base, id] as const,
  library: (base: ChecklistBase) => ['checklists', base, 'library'] as const,
  libraryAll: (base: ChecklistBase) => ['checklists', base, 'library', 'all'] as const,
  reminders: (base: ChecklistBase, id: string) => ['reminders', base, id] as const,
  mine: ['reminders', 'mine'] as const,
};

/** A record's checklists with their items and "done / total". */
export function useChecklists(id: string, base: ChecklistBase = 'incidents', enabled = true) {
  return useQuery({
    queryKey: checklistKeys.of(base, id),
    queryFn: () =>
      call(
        api.GET(at(base, '/api/v1/incidents/{record_id}/checklists'), {
          params: { path: { record_id: id } },
        }),
      ),
    enabled,
  });
}

export type ChecklistChange =
  | { kind: 'add'; title?: string; items?: string[]; libraryId?: string }
  | { kind: 'items'; checklistId: string; items: string[] }
  | { kind: 'tick'; itemId: string; version: number; done: boolean }
  | { kind: 'remove'; checklistId: string; version: number };

/** Add a checklist (typed or from the library), add items, tick one, or remove a checklist.
 * Resolves with how many items were left out by the record's item limit (0 when none). */
export function useChecklistChange(id: string, base: ChecklistBase = 'incidents') {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: async (change: ChecklistChange): Promise<number> => {
      const path = { record_id: id };
      if (change.kind === 'add') {
        const added = await call(
          api.POST(at(base, '/api/v1/incidents/{record_id}/checklists'), {
            params: { path },
            body: {
              title: change.title ?? null,
              items: change.items ?? null,
              library_id: change.libraryId ?? null,
            },
          }),
        );
        return added.dropped;
      }
      if (change.kind === 'items') {
        const added = await call(
          api.POST(at(base, '/api/v1/incidents/{record_id}/checklists/{checklist_id}/items'), {
            params: { path: { ...path, checklist_id: change.checklistId } },
            body: { items: change.items },
          }),
        );
        return added.dropped;
      }
      if (change.kind === 'tick') {
        await call(
          api.PATCH(at(base, '/api/v1/incidents/{record_id}/checklist-items/{item_id}'), {
            params: { path: { ...path, item_id: change.itemId }, header: ifMatch(change.version) },
            body: { done: change.done },
          }),
        );
        return 0;
      }
      await call(
        api.DELETE(at(base, '/api/v1/incidents/{record_id}/checklists/{checklist_id}'), {
          params: {
            path: { ...path, checklist_id: change.checklistId },
            header: ifMatch(change.version),
          },
        }),
      );
      return 0;
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: checklistKeys.of(base, id) });
    },
  });
}

/** Library checklists offered on a record (enabled ones). */
export function useChecklistLibrary(base: ChecklistBase = 'incidents', enabled = true) {
  return useQuery({
    queryKey: checklistKeys.library(base),
    queryFn: () => call(api.GET(at(base, '/api/v1/incidents/checklist-library'))),
    enabled,
    staleTime: 60_000,
  });
}

/** Every library checklist, retired ones too (the admin screen). */
export function useChecklistLibraryAll(base: ChecklistBase = 'incidents') {
  return useQuery({
    queryKey: checklistKeys.libraryAll(base),
    queryFn: () => call(api.GET(at(base, '/api/v1/incidents/checklist-library/all'))),
  });
}

export type LibraryChange =
  | { kind: 'create'; body: components['schemas']['LibraryIn'] }
  | {
      kind: 'update';
      libraryId: string;
      version: number;
      body: components['schemas']['LibraryPatch'];
    };

/** Add or change a library checklist (If-Match on a change). */
export function useLibraryChange(base: ChecklistBase = 'incidents') {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: async (change: LibraryChange): Promise<ChecklistLibraryEntry> =>
      change.kind === 'create'
        ? call(
            api.POST(at(base, '/api/v1/incidents/checklist-library'), {
              body: change.body,
            }),
          )
        : call(
            api.PATCH(at(base, '/api/v1/incidents/checklist-library/{library_id}'), {
              params: {
                path: { library_id: change.libraryId },
                header: ifMatch(change.version),
              },
              body: change.body,
            }),
          ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['checklists', base, 'library'] });
    },
  });
}

/** Read a CSV's items for a library checklist (nothing is saved; the admin reviews first). */
export function useImportChecklistItems(base: ChecklistBase = 'incidents') {
  return useMutation({
    meta: { silent: true },
    mutationFn: (file: File): Promise<ChecklistImport> =>
      call(
        api.POST(at(base, '/api/v1/incidents/checklist-library/import'), {
          // The raw file is the body (no multipart), like the people import (WP-021).
          body: file as unknown as never,
          bodySerializer: (body: unknown) => body as BodyInit,
          headers: { 'Content-Type': 'text/csv' },
        }),
      ),
  });
}

/** Your own reminders on a record (nobody else's, admins included). */
export function useRecordReminders(id: string, base: ChecklistBase = 'incidents', enabled = true) {
  return useQuery({
    queryKey: checklistKeys.reminders(base, id),
    queryFn: () =>
      call(
        api.GET(at(base, '/api/v1/incidents/{record_id}/reminders'), {
          params: { path: { record_id: id } },
        }),
      ),
    enabled,
  });
}

/** Your reminders on every record; `openOnly` false adds the done ones. */
export function useMyReminders(openOnly = true, enabled = true) {
  return useQuery({
    queryKey: [...checklistKeys.mine, openOnly] as const,
    queryFn: () =>
      call(api.GET('/api/v1/my-reminders', { params: { query: { open_only: openOnly } } })),
    enabled,
  });
}

export type ReminderChange =
  | {
      kind: 'add';
      recordId: string;
      base: ChecklistBase;
      body: components['schemas']['ReminderIn'];
    }
  | {
      kind: 'update';
      reminderId: string;
      version: number;
      body: components['schemas']['ReminderPatch'];
    }
  | { kind: 'delete'; reminderId: string; version: number };

/** Set, change, finish or remove one of your reminders. */
export function useReminderChange() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: async (change: ReminderChange): Promise<void> => {
      if (change.kind === 'add') {
        await call(
          api.POST(at(change.base, '/api/v1/incidents/{record_id}/reminders'), {
            params: { path: { record_id: change.recordId } },
            body: change.body,
          }),
        );
      } else if (change.kind === 'update') {
        await call(
          api.PATCH('/api/v1/my-reminders/{reminder_id}', {
            params: { path: { reminder_id: change.reminderId }, header: ifMatch(change.version) },
            body: change.body,
          }),
        );
      } else {
        await call(
          api.DELETE('/api/v1/my-reminders/{reminder_id}', {
            params: { path: { reminder_id: change.reminderId }, header: ifMatch(change.version) },
          }),
        );
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['reminders'] });
    },
  });
}

/** The zip of a record's picked files: a Blob and its file name, for the browser to save. */
export async function downloadRecordArchive(
  recordType: string,
  recordId: string,
  fileIds: string[],
  language: 'en' | 'ar' | 'ur',
): Promise<{ blob: Blob; name: string }> {
  const result = await api.POST('/api/v1/files/records/{record_type}/{record_id}/archive', {
    params: { path: { record_type: recordType, record_id: recordId } },
    body: { file_ids: fileIds, language },
    parseAs: 'blob',
  });
  // A refusal (404, 422, 429) is a problem details body: `call` raises the ApiError as everywhere.
  const blob = await call<Blob>(Promise.resolve(result));
  const disposition = result.response.headers.get('Content-Disposition') ?? '';
  const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? `${recordType}-files.zip`;
  return { blob, name };
}
