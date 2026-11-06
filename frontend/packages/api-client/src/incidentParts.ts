import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// Tasks, worklogs and links of an incident (WP-020e; REQ-INC-067, 072, 084).

export type IncidentTask = components['schemas']['WorkItemTaskOut'];
export type IncidentTasks = components['schemas']['WorkItemTasksOut'];
export type IncidentTaskInput = components['schemas']['WorkItemTaskIn'];
export type IncidentTaskPatch = components['schemas']['WorkItemTaskPatch'];
export type TaskStatus = components['schemas']['TaskStatus'];
export type TaskPriority = components['schemas']['TaskPriority'];
export type MyTask = components['schemas']['WorkItemMyTaskOut'];
export type IncidentWorklog = components['schemas']['WorkItemWorklogOut'];
export type IncidentWorklogs = components['schemas']['WorkItemWorklogsOut'];
export type IncidentWorklogInput = components['schemas']['WorkItemWorklogIn'];
export type WorklogType = components['schemas']['WorklogType'];
export type IncidentLink = components['schemas']['WorkItemLinkOut'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** The work-item types whose record parts (tasks, worklogs, links) these hooks serve. */
export type PartsBase = 'incidents' | 'problems';

/**
 * The same engine route under another type's prefix (WP-044c: problems' tasks and worklogs).
 * The parts routes are generated once per type with identical shapes, so the incident path's
 * types describe them all; only the prefix changes at run time.
 */
function at<P extends string>(base: PartsBase, path: P): P {
  return path.replace('/api/v1/incidents/', `/api/v1/${base}/`) as P;
}

/** A record's tasks in their order, with "done / total". */
export function useIncidentTasks(id: string, enabled = true, base: PartsBase = 'incidents') {
  return useQuery({
    queryKey: queryKeys.incidents.tasks(id),
    queryFn: () =>
      call(
        api.GET(at(base, '/api/v1/incidents/{record_id}/tasks'), {
          params: { path: { record_id: id } },
        }),
      ),
    enabled,
  });
}

export type TaskChange =
  | { kind: 'create'; task: IncidentTaskInput }
  | { kind: 'update'; taskId: string; version: number; task: IncidentTaskPatch }
  | { kind: 'delete'; taskId: string; version: number }
  | { kind: 'move'; taskId: string; direction: 'up' | 'down' };

/** Add, change, remove or move a task of one record. */
export function useTaskChange(id: string, base: PartsBase = 'incidents') {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (change: TaskChange): Promise<void> => {
      const path = { record_id: id };
      if (change.kind === 'create') {
        await call(
          api.POST(at(base, '/api/v1/incidents/{record_id}/tasks'), {
            params: { path },
            body: change.task,
          }),
        );
      } else if (change.kind === 'update') {
        await call(
          api.PATCH(at(base, '/api/v1/incidents/{record_id}/tasks/{task_id}'), {
            params: { path: { ...path, task_id: change.taskId }, header: ifMatch(change.version) },
            body: change.task,
          }),
        );
      } else if (change.kind === 'delete') {
        await call(
          api.DELETE(at(base, '/api/v1/incidents/{record_id}/tasks/{task_id}'), {
            params: { path: { ...path, task_id: change.taskId }, header: ifMatch(change.version) },
          }),
        );
      } else {
        await call(
          api.POST(at(base, '/api/v1/incidents/{record_id}/tasks/{task_id}/move'), {
            params: { path: { ...path, task_id: change.taskId } },
            body: { direction: change.direction },
          }),
        );
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.tasks(id) });
    },
  });
}

/** Open tasks you own, with their records. */
export function useMyTasks(enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.myTasks,
    queryFn: () => call(api.GET('/api/v1/incidents/my-tasks')),
    enabled,
  });
}

/** A record's worklogs with totals per person and per type. */
export function useIncidentWorklogs(id: string, enabled = true, base: PartsBase = 'incidents') {
  return useQuery({
    queryKey: queryKeys.incidents.worklogs(id),
    queryFn: () =>
      call(
        api.GET(at(base, '/api/v1/incidents/{record_id}/worklogs'), {
          params: { path: { record_id: id } },
        }),
      ),
    enabled,
  });
}

export type WorklogChange =
  | { kind: 'create'; worklog: IncidentWorklogInput }
  | { kind: 'delete'; worklogId: string; version: number };

/** Log time on a record, or remove a worklog. */
export function useWorklogChange(id: string, base: PartsBase = 'incidents') {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (change: WorklogChange): Promise<void> => {
      if (change.kind === 'create') {
        await call(
          api.POST(at(base, '/api/v1/incidents/{record_id}/worklogs'), {
            params: { path: { record_id: id } },
            body: change.worklog,
          }),
        );
        return;
      }
      await call(
        api.DELETE(at(base, '/api/v1/incidents/{record_id}/worklogs/{worklog_id}'), {
          params: {
            path: { record_id: id, worklog_id: change.worklogId },
            header: ifMatch(change.version),
          },
        }),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.worklogs(id) });
    },
  });
}

/** Both sides of a record's links. */
export function useIncidentLinks(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.links(id),
    queryFn: () =>
      call(api.GET('/api/v1/incidents/{record_id}/links', { params: { path: { record_id: id } } })),
    enabled,
  });
}

export type LinkChange =
  | { kind: 'create'; otherId: string; comment: string | null }
  | { kind: 'delete'; linkId: string; version: number };

/** Link a related record, or remove a link (from either side). */
export function useLinkChange(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (change: LinkChange): Promise<void> => {
      if (change.kind === 'create') {
        await call(
          api.POST('/api/v1/incidents/{record_id}/links', {
            params: { path: { record_id: id } },
            body: { other_id: change.otherId, comment: change.comment },
          }),
        );
        return;
      }
      await call(
        api.DELETE('/api/v1/incidents/{record_id}/links/{link_id}', {
          params: {
            path: { record_id: id, link_id: change.linkId },
            header: ifMatch(change.version),
          },
        }),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.links(id) });
    },
  });
}
