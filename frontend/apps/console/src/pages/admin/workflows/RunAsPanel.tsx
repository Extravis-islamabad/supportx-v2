import { Typography } from 'antd';

import { useRunAs, useSetRunAsRole, type WorkflowOut } from '@supportx/api-client';
import { ServiceRolesSection, reportError, useLabel } from '@supportx/ui';

/**
 * Who the workflow's steps act as, and its roles (REQ-WF-010; ADR-043 §6), through the shared
 * service-identity roles section: roles come only from the server's list of roles a run-as
 * identity may hold, never above the admin's own rights. Live through the designer's channel.
 */
export function RunAsPanel({ workflow, readOnly }: { workflow: WorkflowOut; readOnly: boolean }) {
  const t = useLabel();
  const runAs = useRunAs(workflow.id);
  const set = useSetRunAsRole();
  if (runAs.data === undefined) return null;
  const change = (roleId: string, held: boolean) => {
    set.mutate({ workflowId: workflow.id, roleId, held }, { onError: reportError });
  };
  return (
    <ServiceRolesSection
      data={runAs.data}
      readOnly={readOnly}
      pending={set.isPending}
      onGive={(roleId) => {
        change(roleId, true);
      }}
      onTake={(roleId) => {
        change(roleId, false);
      }}
      notMade={t('workflows.run_as.not_made')}
      help={
        <>
          <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
            {t('workflows.run_as.help')}
          </Typography.Paragraph>
          <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
            {t('workflows.run_as.scope_help')}
          </Typography.Paragraph>
        </>
      }
      testId="designer-run-as"
    />
  );
}
