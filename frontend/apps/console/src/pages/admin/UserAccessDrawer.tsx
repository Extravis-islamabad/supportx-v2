import { PlusOutlined } from '@ant-design/icons';
import {
  Button,
  Checkbox,
  Drawer,
  Empty,
  Flex,
  Input,
  Select,
  Space,
  Spin,
  Typography,
} from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  queryKeys,
  useRoleAssignment,
  useRoles,
  useUnitMutations,
  useUnits,
  useUserAccess,
  type UnitKind,
  type UserDetail,
} from '@supportx/api-client';
import { refreshList, useRealtimeUser, useRecordChannel } from '@supportx/realtime';
import { PresenceAvatars, useAccess, useLabel } from '@supportx/ui';

import { roleName } from './roleName';

export interface UserAccessDrawerProps {
  user: UserDetail | undefined;
  onClose: () => void;
}

/**
 * One user's roles, sites and support groups (WP-016). Editable with users.manage (roles),
 * sites.manage / groups.manage (memberships); read-only otherwise. The server refuses anything
 * the editor may not grant (privilege escalation, last tenant admin) with a translated message.
 */
export function UserAccessDrawer({ user, onClose }: UserAccessDrawerProps) {
  const t = useLabel();
  return (
    <Drawer
      open={user !== undefined}
      onClose={onClose}
      width={480}
      title={user === undefined ? undefined : t('access.title', { name: user.display_name })}
      destroyOnHidden
    >
      {user === undefined ? <Spin /> : <UserAccessPanel user={user} />}
    </Drawer>
  );
}

/** The roles, sites and groups of one user (also the person drawer's Access tab, WP-021). */
export function UserAccessPanel({ user }: { user: UserDetail }) {
  const access = useUserAccess(user.id);
  // Live (WP-011): roles or memberships changed by another admin show at once; and who else
  // has this user open.
  const queryClient = useQueryClient();
  const viewers = useRecordChannel('users', user.id, () => {
    refreshList(queryClient, queryKeys.access.user(user.id));
  });
  const self = useRealtimeUser();
  if (access.data === undefined) return <Spin />;
  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }} data-testid="user-access">
      <PresenceAvatars viewers={viewers} selfUserId={self} />
      <RolesSection userId={user.id} roleIds={access.data.role_ids} />
      <UnitsSection kind="sites" userId={user.id} memberOf={access.data.site_ids} />
      <UnitsSection kind="groups" userId={user.id} memberOf={access.data.group_ids} />
    </Space>
  );
}

function RolesSection({ userId, roleIds }: { userId: string; roleIds: string[] }) {
  const t = useLabel();
  const { can } = useAccess();
  const roles = useRoles(can('roles.view'));
  const { assign, remove } = useRoleAssignment();
  const editable = can('users.manage');
  const busy = assign.isPending || remove.isPending;
  return (
    <section aria-labelledby="access-roles">
      <Typography.Title level={4} id="access-roles">
        {t('access.roles')}
      </Typography.Title>
      {roles.data === undefined ? (
        <Spin size="small" />
      ) : (
        <Flex vertical gap={8}>
          {roles.data.map((role) => (
            <Checkbox
              key={role.id}
              data-testid={`role-checkbox-${role.key}`}
              checked={roleIds.includes(role.id)}
              disabled={!editable || busy}
              onChange={(event) => {
                const variables = { userId, roleId: role.id };
                if (event.target.checked) assign.mutate(variables);
                else remove.mutate(variables);
              }}
            >
              {roleName(role, t)}
            </Checkbox>
          ))}
        </Flex>
      )}
    </section>
  );
}

function UnitsSection({
  kind,
  userId,
  memberOf,
}: {
  kind: UnitKind;
  userId: string;
  memberOf: string[];
}) {
  const t = useLabel();
  const { can } = useAccess();
  const units = useUnits(kind, can(`${kind}.view`));
  const { create, membership } = useUnitMutations(kind);
  const [name, setName] = useState('');
  const editable = can(`${kind}.manage`);
  const titleId = `access-${kind}`;
  return (
    <section aria-labelledby={titleId}>
      <Typography.Title level={4} id={titleId}>
        {t(`access.${kind}`)}
      </Typography.Title>
      {units.data === undefined ? (
        <Spin size="small" />
      ) : units.data.length === 0 && !editable ? (
        <Empty description={t('access.none')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Select
          mode="multiple"
          aria-labelledby={titleId}
          data-testid={`access-${kind}-select`}
          style={{ width: '100%' }}
          value={memberOf}
          disabled={!editable || membership.isPending}
          placeholder={t('access.none')}
          options={units.data.map((unit) => ({ value: unit.id, label: unit.name }))}
          onSelect={(unitId: string) => {
            membership.mutate({ unitId, userId, member: true });
          }}
          onDeselect={(unitId: string) => {
            membership.mutate({ unitId, userId, member: false });
          }}
        />
      )}
      {editable && (
        <Space.Compact style={{ width: '100%', marginTop: 8 }}>
          <Input
            aria-label={t(`access.new_${kind}`)}
            placeholder={t(`access.new_${kind}`)}
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
          <Button
            icon={<PlusOutlined />}
            disabled={name.trim() === ''}
            loading={create.isPending}
            onClick={() => {
              create.mutate(name.trim(), {
                onSuccess: (unit) => {
                  setName('');
                  membership.mutate({ unitId: unit.id, userId, member: true });
                },
              });
            }}
          >
            {t('actions.add')}
          </Button>
        </Space.Compact>
      )}
    </section>
  );
}
