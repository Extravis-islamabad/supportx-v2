import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// Visual workflows (WP-048b S4; ADR-043): the list, the designer and test mode. Writes carry
// the workflow's If-Match; every change reaches other admins through the workflows list channel.

export type WorkflowOut = components['schemas']['WorkflowOut'];
export type WorkflowProblem = components['schemas']['ProblemOut'];
export type NodeTypeOut = components['schemas']['NodeTypeOut'];
export type NodePortsOut = components['schemas']['NodePortsOut'];
export type NodeConfigIn = components['schemas']['NodeConfigIn'];
export type TestRunOut = components['schemas']['TestRunOut'];
export type TestRunIn = components['schemas']['TestRunIn'];
export type TestAnswerIn = components['schemas']['AnswerIn'];

const PATH = '/api/v1/automation/workflows';

function ifMatch(version: number) {
  return { 'If-Match': `"${String(version)}"` };
}

/** A record type's workflows, by name. */
export function useWorkflows(recordType: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.workflows.list(recordType),
    queryFn: () => call(api.GET(PATH, { params: { query: { record_type: recordType } } })),
    enabled,
  });
}

/** One workflow with its draft and the draft's problems. */
export function useWorkflow(id: string) {
  return useQuery({
    queryKey: queryKeys.workflows.detail(id),
    queryFn: () =>
      call(api.GET(`${PATH}/{workflow_id}`, { params: { path: { workflow_id: id } } })),
    enabled: id !== '',
  });
}

/** The palette for a record type: each node type, its group, and whether it can be used now. */
export function useNodeTypes(recordType: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.workflows.nodeTypes(recordType),
    queryFn: () =>
      call(api.GET(`${PATH}/node-types`, { params: { query: { record_type: recordType } } })),
    enabled,
    staleTime: 5 * 60_000, // the registry changes with a release, a licence or a runner
  });
}

/** The outputs of nodes being designed, from the server's registry (changes nothing). */
export function useNodePorts() {
  return useMutation({
    mutationFn: (nodes: NodeConfigIn[]) =>
      call(api.POST(`${PATH}/node-ports`, { body: { nodes } })),
  });
}

function useRefresh() {
  const queryClient = useQueryClient();
  return (saved?: WorkflowOut) => {
    if (saved !== undefined) queryClient.setQueryData(queryKeys.workflows.detail(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: ['workflows', 'list'] });
  };
}

/** Add a workflow (one Idempotency-Key per form). */
export function useCreateWorkflow() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ key, recordType, name }: { key: string; recordType: string; name: string }) =>
      call(
        api.POST(PATH, {
          params: { header: { 'Idempotency-Key': key } },
          body: { record_type: recordType, name },
        }),
      ),
    onSuccess: (saved) => {
      refresh(saved);
    },
  });
}

/** Save the draft, problems and all; they come back for the canvas to mark (REQ-WF-019). */
export function useSaveDraft() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({
      id,
      version,
      definition,
    }: {
      id: string;
      version: number;
      definition: Record<string, unknown>;
    }) =>
      call(
        api.PUT(`${PATH}/{workflow_id}/draft`, {
          params: { path: { workflow_id: id }, header: ifMatch(version) },
          body: { definition },
        }),
      ),
    onSuccess: (saved) => {
      refresh(saved);
    },
  });
}

/** Publish the draft as the next version (refused while it has problems). */
export function usePublishWorkflow() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.POST(`${PATH}/{workflow_id}/publish`, {
          params: { path: { workflow_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: (saved) => {
      refresh(saved);
    },
  });
}

/** Switch a workflow on or off. */
export function useEnableWorkflow() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, version, enabled }: { id: string; version: number; enabled: boolean }) =>
      call(
        api.PUT(`${PATH}/{workflow_id}/enabled`, {
          params: { path: { workflow_id: id }, header: ifMatch(version) },
          body: { enabled },
        }),
      ),
    onSuccess: (saved) => {
      refresh(saved);
    },
  });
}

/** Copy a workflow as an independent draft under a new name (REQ-WF-027 AC1). */
export function useCopyWorkflow() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, key, name }: { id: string; key: string; name: string }) =>
      call(
        api.POST(`${PATH}/{workflow_id}/copy`, {
          params: { path: { workflow_id: id }, header: { 'Idempotency-Key': key } },
          body: { name },
        }),
      ),
    onSuccess: (saved) => {
      refresh(saved);
    },
  });
}

/** Delete a workflow without live runs (REQ-WF-027 AC3). */
export function useDeleteWorkflow() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE(`${PATH}/{workflow_id}`, {
          params: { path: { workflow_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: () => {
      refresh();
    },
  });
}

/** Start a test run of the draft on a record or on sample values (REQ-WF-022). */
export function useStartTestRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, key, body }: { id: string; key: string; body: TestRunIn }) =>
      call(
        api.POST(`${PATH}/{workflow_id}/test-runs`, {
          params: { path: { workflow_id: id }, header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSuccess: (run) => {
      queryClient.setQueryData(queryKeys.workflows.testRun(run.id), run);
    },
  });
}

/** One test run: its steps, what it waits for, its variables. */
export function useTestRun(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.workflows.testRun(id ?? ''),
    queryFn: () =>
      call(api.GET(`${PATH}/test-runs/{run_id}`, { params: { path: { run_id: id ?? '' } } })),
    enabled: id !== undefined,
  });
}

/** Answer a test run: a shown command, a described change, or the clock moved on. */
export function useAnswerTestRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ run, body }: { run: TestRunOut; body: TestAnswerIn }) =>
      call(
        api.POST(`${PATH}/test-runs/{run_id}/answer`, {
          params: { path: { run_id: run.id }, header: ifMatch(run.version) },
          body,
        }),
      ),
    onSuccess: (run) => {
      queryClient.setQueryData(queryKeys.workflows.testRun(run.id), run);
    },
  });
}

/** The run's one live call, for a webhook or notify node (audited by the server). */
export function useLiveCall() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ run, commandId }: { run: TestRunOut; commandId: string }) =>
      call(
        api.POST(`${PATH}/test-runs/{run_id}/live-call`, {
          params: { path: { run_id: run.id }, header: ifMatch(run.version) },
          body: { command_id: commandId },
        }),
      ),
    onSuccess: (run) => {
      queryClient.setQueryData(queryKeys.workflows.testRun(run.id), run);
    },
  });
}

/** A workflow's file (REQ-WF-027 AC2): the definition and what it needs, naming its tenant. */
export function useExportWorkflow() {
  return useMutation({
    mutationFn: (id: string) =>
      call(api.GET(`${PATH}/{workflow_id}/export`, { params: { path: { workflow_id: id } } })),
  });
}

/** Import a file exported here as a new, disabled draft (same tenant only). */
export function useImportWorkflow() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ key, file }: { key: string; file: Record<string, unknown> }) =>
      call(
        api.POST(`${PATH}/import`, {
          params: { header: { 'Idempotency-Key': key } },
          // The server checks the file against its closed schema (and its size) itself.
          body: file as never,
        }),
      ),
    onSuccess: (saved) => {
      refresh(saved);
    },
  });
}

/** A record of a workflow's type by its display ID (INC-12), for a test run on it. */
export function useFindRecord() {
  return useMutation({
    mutationFn: async ({ type, value }: { type: string; value: string }): Promise<string> => {
      const path = { params: { path: { value } } };
      const found =
        type === 'incident'
          ? await call(api.GET('/api/v1/incidents/lookup/{value}', path))
          : type === 'service_request'
            ? await call(api.GET('/api/v1/service-requests/lookup/{value}', path))
            : type === 'problem'
              ? await call(api.GET('/api/v1/problems/lookup/{value}', path))
              : type === 'change'
                ? await call(api.GET('/api/v1/changes/lookup/{value}', path))
                : await call(api.GET('/api/v1/releases/lookup/{value}', path));
      return found.id;
    },
  });
}

export type RecordWorkflowOut = components['schemas']['RecordWorkflowOut'];

/** The workflows on a record, for its panel: each run's diagram, position and log. */
export function useRecordWorkflows(recordType: string, recordId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.workflows.record(recordType, recordId),
    queryFn: () =>
      call(
        api.GET(`${PATH}/records/{record_type}/{record_id}`, {
          params: { path: { record_type: recordType, record_id: recordId } },
        }),
      ),
    enabled: enabled && recordId !== '',
  });
}

function useRecordRefresh() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ['workflows', 'record'] });
  };
}

/** Stop a run on a record, with a reason (REQ-WF-026 AC1). */
export function useStopInstance() {
  const refresh = useRecordRefresh();
  return useMutation({
    mutationFn: ({ id, version, reason }: { id: string; version: number; reason: string }) =>
      call(
        api.POST(`${PATH}/instances/{instance_id}/stop`, {
          params: { path: { instance_id: id }, header: ifMatch(version) },
          body: { reason },
        }),
      ),
    onSettled: refresh,
  });
}

/** Run it again, from the start or a chosen node (REQ-WF-026 AC2). */
export function useRestartInstance() {
  const refresh = useRecordRefresh();
  return useMutation({
    mutationFn: ({ id, version, node }: { id: string; version: number; node?: string }) =>
      call(
        api.POST(`${PATH}/instances/{instance_id}/restart`, {
          params: { path: { instance_id: id }, header: ifMatch(version) },
          body: { node: node ?? null },
        }),
      ),
    onSettled: refresh,
  });
}

/** Run a failed step again (REQ-WF-024 AC2). */
export function useRetryInstance() {
  const refresh = useRecordRefresh();
  return useMutation({
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.POST(`${PATH}/instances/{instance_id}/retry`, {
          params: { path: { instance_id: id }, header: ifMatch(version) },
        }),
      ),
    onSettled: refresh,
  });
}
