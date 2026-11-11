import { Alert, Flex, Select, Tag, Typography } from 'antd';

import { useRunAs, useSetRunAsRole, type WorkflowOut } from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import { EmptyText, reportError, useLabel } from '@supportx/ui';
import { useQueryClient } from '@tanstack/react-query';

import { named } from './runAs';

/**
 * Who the workflow's steps act as, and its roles (REQ-WF-010; ADR-043 §6). Roles are given only
 * from the server's own list of roles a run-as identity may hold, never above the admin's own
 * rights; a role given or taken shows live for every admin with the designer open.
 */
export function RunAsPanel({ workflow, readOnly }: { workflow: WorkflowOut; readOnly: boolean }) {
  const t = useLabel();
  const queryClient = useQueryClient();
  const runAs = useRunAs(workflow.id);
  const set = useSetRunAsRole();
  useListChannel('workflows', (m) => {
    if (m.type === 'workflows.changed' && m.ids.includes(workflow.id)) {
      void queryClient.invalidateQueries({ queryKey: ['workflows', 'run-as', workflow.id] });
    }
  });
  const data = runAs.data;
  if (data === undefined) return null;
  const held = new Set(data.roles.map((r) => r.id));
  const change = (roleId: string, give: boolean) => {
    set.mutate({ workflowId: workflow.id, roleId, held: give }, { onError: reportError });
  };
  return (
    <Flex vertical gap={12} data-testid="designer-run-as">
      <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
        {t('workflows.run_as.help')}
      </Typography.Paragraph>
      <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
        {t('workflows.run_as.scope_help')}
      </Typography.Paragraph>
      {!data.made ? (
        <EmptyText>{t('workflows.run_as.not_made')}</EmptyText>
      ) : (
        <>
          <Typography.Text strong data-testid="run-as-name">
            <bdi dir="auto">{data.name}</bdi>
          </Typography.Text>
          {!data.active && (
            <Typography.Text type="secondary">{t('workflows.run_as.inactive')}</Typography.Text>
          )}
          {data.roles.length === 0 ? (
            <Alert type="warning" showIcon message={t('workflows.run_as.no_roles')} />
          ) : (
            <Flex wrap gap={4} data-testid="run-as-roles">
              {data.roles.map((role) => (
                <Tag
                  key={role.id}
                  closable={!readOnly}
                  onClose={(event) => {
                    event.preventDefault();
                    change(role.id, false);
                  }}
                  closeIcon={
                    <span aria-label={t('workflows.run_as.remove', { name: named(t, role) })}>
                      ×
                    </span>
                  }
                >
                  {named(t, role)}
                </Tag>
              ))}
            </Flex>
          )}
          <Select<string>
            value={null}
            disabled={readOnly || set.isPending}
            placeholder={t('workflows.run_as.add')}
            aria-label={t('workflows.run_as.add')}
            showSearch
            optionFilterProp="label"
            onChange={(roleId) => {
              change(roleId, true);
            }}
            options={data.offered
              .filter((r) => !held.has(r.id))
              .map((r) => ({ value: r.id, label: named(t, r) }))}
            notFoundContent={t('workflows.run_as.none_offered')}
            data-testid="run-as-add"
          />
        </>
      )}
    </Flex>
  );
}
