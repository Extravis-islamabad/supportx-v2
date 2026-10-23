import { PlusOutlined } from '@ant-design/icons';
import { Badge, Flex, Table, Typography } from 'antd';
import { useState } from 'react';

import { useRoles, type RoleSummary } from '@supportx/api-client';
import { NoAccess, useAccess, useLabel, WriteButton } from '@supportx/ui';

import { RoleEditor } from './RoleEditor';
import { roleName } from './roleName';

/** Admin › Roles: system roles (read-only) and custom roles with their user counts (WP-016). */
export function RolesPage() {
  const t = useLabel();
  const { can } = useAccess();
  const allowed = can('roles.view');
  const roles = useRoles(allowed);
  // undefined = closed; null = a new role; a role = edit (or view, for system roles).
  const [editing, setEditing] = useState<RoleSummary | null>();

  if (!allowed) return <NoAccess titleKey="nav.admin_roles" />;

  return (
    <>
      <Flex justify="space-between" align="baseline" style={{ marginBottom: 16 }}>
        <Typography.Title level={2} style={{ margin: 0 }}>
          {t('roles.title')}
        </Typography.Title>
        {can('roles.manage') && (
          <WriteButton
            type="primary"
            icon={<PlusOutlined />}
            data-testid="new-role"
            onClick={() => {
              setEditing(null);
            }}
          >
            {t('roles.new')}
          </WriteButton>
        )}
      </Flex>
      <Table<RoleSummary>
        rowKey="id"
        data-testid="roles-table"
        loading={roles.isPending}
        dataSource={roles.data ?? []}
        pagination={false}
        onRow={(role) => ({
          onClick: () => {
            setEditing(role);
          },
          style: { cursor: 'pointer' },
          'data-testid': `role-row-${role.key}`,
        })}
        columns={[
          {
            key: 'name',
            title: t('roles.col.name'),
            render: (_, role) => (
              <Flex vertical>
                <Typography.Text strong>{roleName(role, t)}</Typography.Text>
                <Typography.Text type="secondary">
                  {role.is_system ? t(`role.${role.key}.description`) : (role.description ?? '')}
                </Typography.Text>
              </Flex>
            ),
          },
          {
            key: 'type',
            title: t('roles.col.type'),
            render: (_, role) => (
              <Badge
                status={role.is_system ? 'default' : 'processing'}
                text={t(role.is_system ? 'roles.type.system' : 'roles.type.custom')}
              />
            ),
          },
          { key: 'users', title: t('roles.col.users'), render: (_, role) => role.user_count },
        ]}
      />
      <RoleEditor
        role={editing}
        onClose={() => {
          setEditing(undefined);
        }}
      />
    </>
  );
}
