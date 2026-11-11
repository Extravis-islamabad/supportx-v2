// The record types a workflow can run on (the work item types that register workflow ports).
export const WORKFLOW_TYPES = [
  'incident',
  'service_request',
  'problem',
  'change',
  'release',
] as const;
export type WorkflowType = (typeof WORKFLOW_TYPES)[number];
