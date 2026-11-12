import { Form, Modal, Select, Typography } from 'antd';
import { useState } from 'react';

import { useRoleCandidates, useStartBulk } from '@supportx/api-client';
import { FormProblem, useFormProblem, useLabel } from '@supportx/ui';

// The two roles the list assigns in bulk (REQ-REL-057): who runs the release, and who deploys it.
const ROLES = ['release_manager', 'release_engineer'] as const;
type Role = (typeof ROLES)[number];

/**
 * Give the picked releases one person in one role (REQ-REL-057): each release is changed as you,
 * by the Roles tab's own rules, so one you may not change, or where the person may not hold the
 * role, is skipped and the progress drawer says why. Only people the role allows are offered.
 */
export function ReleaseBulkRole({
  ids,
  open,
  onClose,
  onStarted,
}: {
  ids: string[];
  open: boolean;
  onClose: () => void;
  onStarted: (jobId: string) => void;
}) {
  const t = useLabel();
  const [role, setRole] = useState<Role>('release_engineer');
  const [person, setPerson] = useState<string | undefined>(undefined);
  const [search, setSearch] = useState('');
  const candidates = useRoleCandidates(role, search, open);
  const start = useStartBulk('releases');
  const problem = useFormProblem();
  const reset = () => {
    setPerson(undefined);
    setSearch('');
    problem.clear();
  };
  return (
    <Modal
      open={open}
      title={t('releases.bulk.title.assign_role', { count: ids.length })}
      okText={t('incidents.bulk.action.assign_role')}
      cancelText={t('incidents.bulk.cancel')}
      okButtonProps={{ disabled: person === undefined, 'data-testid': 'rel-bulk-role-ok' }}
      confirmLoading={start.isPending}
      onCancel={() => {
        reset();
        onClose();
      }}
      onOk={() => {
        if (person === undefined) return;
        start.mutate(
          { action: 'assign_role', recordIds: ids, changes: { role, user_ids: [person] } },
          {
            onSuccess: (job) => {
              reset();
              onStarted(job.id);
            },
            onError: (error) => {
              problem.show(error);
            },
          },
        );
      }}
      data-testid="rel-bulk-role"
    >
      <Typography.Paragraph type="secondary">{t('releases.bulk.role_help')}</Typography.Paragraph>
      <Form layout="vertical">
        <Form.Item label={t('releases.bulk.role')} htmlFor="rel-bulk-role-code" required>
          <Select<Role>
            id="rel-bulk-role-code"
            value={role}
            onChange={(next) => {
              setRole(next);
              setPerson(undefined); // who may hold one role may not hold the other
            }}
            options={ROLES.map((code) => ({ value: code, label: t(`work_item_role.${code}`) }))}
            data-testid="rel-bulk-role-code"
          />
        </Form.Item>
        <Form.Item label={t('releases.bulk.person')} htmlFor="rel-bulk-role-person" required>
          <Select
            id="rel-bulk-role-person"
            showSearch
            filterOption={false}
            value={person}
            onSearch={setSearch}
            onChange={setPerson}
            loading={candidates.isFetching}
            options={(candidates.data ?? []).map((p) => ({ value: p.id, label: p.name }))}
            data-testid="rel-bulk-role-person"
          />
        </Form.Item>
      </Form>
      <FormProblem problem={problem} />
    </Modal>
  );
}
