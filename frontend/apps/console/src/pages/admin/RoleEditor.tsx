import { LockOutlined } from '@ant-design/icons';
import {
  Alert,
  App,
  Button,
  Collapse,
  Drawer,
  Flex,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';

import {
  ApiError,
  usePermissionCatalogue,
  useRole,
  useRoleMutations,
  useRoles,
  type PermissionInfo,
  type RoleDetail,
  type RoleGrant,
  type RoleSummary,
  type Scope,
} from '@supportx/api-client';
import { reportError, useAccess, useLabel, WriteButton, lengthLimit } from '@supportx/ui';

import { roleName } from './roleName';

type Matrix = Record<string, RoleGrant | undefined>;
const NONE = 'none';

export interface RoleEditorProps {
  /** undefined = closed; null = new custom role; otherwise the role to edit or view. */
  role: RoleSummary | null | undefined;
  onClose: () => void;
}

/**
 * Create or edit a custom role: name, description and a permission matrix grouped by module
 * (rows = permissions, one scope per permission). Permissions outside the plan are locked.
 * System roles open read-only. The server refuses grants beyond the editor's own permissions.
 */
export function RoleEditor({ role, onClose }: RoleEditorProps) {
  const t = useLabel();
  const catalogue = usePermissionCatalogue(role !== undefined);
  const detail = useRole(role?.id);
  const initial = role === null ? null : detail.data;
  const ready = catalogue.data !== undefined && initial !== undefined;
  return (
    <Drawer
      open={role !== undefined}
      onClose={onClose}
      width={760}
      destroyOnHidden
      title={
        role === null
          ? t('roles.editor.new')
          : role === undefined
            ? undefined
            : t('roles.editor.edit', { name: roleName(role, t) })
      }
    >
      {role !== undefined && ready ? (
        <RoleForm
          key={role?.id ?? 'new'}
          role={role}
          initial={initial}
          catalogue={catalogue.data}
          onClose={onClose}
        />
      ) : (
        <Spin />
      )}
    </Drawer>
  );
}

function RoleForm({
  role,
  initial,
  catalogue,
  onClose,
}: {
  role: RoleSummary | null;
  initial: RoleDetail | null;
  catalogue: PermissionInfo[];
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const { can } = useAccess();
  const { create, update, remove } = useRoleMutations();
  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [matrix, setMatrix] = useState<Matrix>(() =>
    Object.fromEntries((initial?.permissions ?? []).map((g) => [g.permission, g])),
  );
  const [deleting, setDeleting] = useState(false);
  // The version this form was filled from: the save sends it, so a role saved elsewhere meanwhile
  // is refused, never overwritten (QA WP-026 BUG-01); the change is announced at once.
  const [base] = useState(initial?.version ?? 0);
  const stale = initial !== null && initial.version !== base;
  const readOnly = role?.is_system === true || !can('roles.manage');
  const modules = useMemo(() => groupByModule(catalogue), [catalogue]);

  const save = () => {
    const permissions = Object.values(matrix).filter((g): g is RoleGrant => g !== undefined);
    const body = { name, description: description === '' ? null : description, permissions };
    const done = () => {
      void message.success(t('roles.saved'));
      onClose();
    };
    if (initial === null) {
      create.mutate(body, { onSuccess: done, onError: reportError });
    } else {
      update.mutate(
        { id: initial.id, version: base, body },
        {
          onSuccess: done,
          onError: (error) => {
            if (error instanceof ApiError && error.code === 'version_conflict') {
              void message.warning(t('settings.changed_elsewhere'));
              return;
            }
            reportError(error);
          },
        },
      );
    }
  };

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {role?.is_system === true && (
        <Alert type="info" showIcon message={t('roles.system_read_only')} />
      )}
      {stale && role?.is_system !== true && (
        <Alert
          type="warning"
          showIcon
          role="status"
          message={t('settings.stale')}
          data-testid="role-stale"
        />
      )}
      {role?.is_system !== true && (
        <Form layout="vertical">
          <Form.Item label={t('roles.name')} htmlFor="role-name" required>
            <Input
              id="role-name"
              data-testid="role-name"
              value={name}
              count={lengthLimit(200)}
              disabled={readOnly}
              onChange={(event) => {
                setName(event.target.value);
              }}
            />
          </Form.Item>
          <Form.Item label={t('roles.description')} htmlFor="role-description">
            <Input.TextArea
              id="role-description"
              value={description}
              count={lengthLimit(1000)}
              rows={2}
              disabled={readOnly}
              onChange={(event) => {
                setDescription(event.target.value);
              }}
            />
          </Form.Item>
        </Form>
      )}
      <Typography.Title level={4}>{t('roles.permissions')}</Typography.Title>
      <Collapse
        defaultActiveKey={modules.map(([module]) => module)}
        items={modules.map(([module, permissions]) => ({
          key: module,
          label: t(`permission_module.${module}`),
          children: (
            <PermissionRows
              permissions={permissions}
              matrix={matrix}
              readOnly={readOnly}
              onChange={(key, grant) => {
                setMatrix((current) => ({ ...current, [key]: grant }));
              }}
            />
          ),
        }))}
      />
      {!readOnly && (
        <Flex justify="end" gap={8}>
          {role !== null && (
            <Button
              danger
              data-testid="delete-role"
              onClick={() => {
                setDeleting(true);
              }}
            >
              {t('roles.delete')}
            </Button>
          )}
          <WriteButton
            type="primary"
            data-testid="save-role"
            loading={create.isPending || update.isPending}
            disabled={name.trim() === ''}
            onClick={save}
          >
            {t('actions.save')}
          </WriteButton>
        </Flex>
      )}
      {role !== null && initial !== null && (
        <DeleteRoleDialog
          open={deleting}
          role={role}
          version={initial.version}
          onCancel={() => {
            setDeleting(false);
          }}
          onDeleted={() => {
            setDeleting(false);
            void message.success(t('roles.deleted'));
            onClose();
          }}
          remove={remove}
        />
      )}
    </Space>
  );
}

function groupByModule(catalogue: PermissionInfo[]): [string, PermissionInfo[]][] {
  const groups = new Map<string, PermissionInfo[]>();
  for (const permission of catalogue) {
    groups.set(permission.module, [...(groups.get(permission.module) ?? []), permission]);
  }
  return [...groups.entries()];
}

function PermissionRows({
  permissions,
  matrix,
  readOnly,
  onChange,
}: {
  permissions: PermissionInfo[];
  matrix: Matrix;
  readOnly: boolean;
  onChange: (key: string, grant: RoleGrant | undefined) => void;
}) {
  const t = useLabel();
  return (
    <Table<PermissionInfo>
      rowKey="key"
      size="small"
      pagination={false}
      showHeader={false}
      dataSource={permissions}
      columns={[
        {
          key: 'permission',
          render: (_, permission) => (
            <Flex vertical>
              <Typography.Text strong>
                {t(`permission.${permission.key}`)}{' '}
                {!permission.entitled && (
                  <Tooltip title={t('licence.upgrade_hint')}>
                    <LockOutlined aria-label={t('licence.locked')} />
                  </Tooltip>
                )}
              </Typography.Text>
              <Typography.Text type="secondary">
                {t(`permission.${permission.key}.description`)}
              </Typography.Text>
              {matrix[permission.key]?.condition != null && <Tag>{t('roles.has_rule')}</Tag>}
            </Flex>
          ),
        },
        {
          key: 'scope',
          width: 200,
          render: (_, permission) => {
            const grant = matrix[permission.key];
            return (
              <Select<string>
                aria-label={t('roles.scope_of', { permission: t(`permission.${permission.key}`) })}
                data-testid={`scope-${permission.key}`}
                style={{ width: '100%' }}
                value={grant?.scope ?? NONE}
                disabled={readOnly || !permission.entitled}
                options={[
                  { value: NONE, label: t('scope.none') },
                  ...permission.scopes.map((scope) => ({
                    value: scope,
                    label: t(`scope.${scope}`),
                  })),
                ]}
                onChange={(value) => {
                  onChange(
                    permission.key,
                    value === NONE
                      ? undefined
                      : {
                          permission: permission.key,
                          scope: value as Scope,
                          condition: grant?.condition ?? null,
                        },
                  );
                }}
              />
            );
          },
        },
      ]}
    />
  );
}

function DeleteRoleDialog({
  open,
  role,
  version,
  onCancel,
  onDeleted,
  remove,
}: {
  open: boolean;
  role: RoleSummary;
  version: number;
  onCancel: () => void;
  onDeleted: () => void;
  remove: ReturnType<typeof useRoleMutations>['remove'];
}) {
  const t = useLabel();
  const roles = useRoles(open);
  const [target, setTarget] = useState<string>();
  const inUse = role.user_count > 0;
  return (
    <Modal
      open={open}
      title={t('roles.delete_title', { name: role.name })}
      okText={t('roles.delete')}
      okButtonProps={{
        danger: true,
        disabled: inUse && target === undefined,
        loading: remove.isPending,
      }}
      cancelText={t('actions.cancel')}
      onCancel={onCancel}
      onOk={() => {
        remove.mutate(
          { id: role.id, version, reassignTo: target },
          { onSuccess: onDeleted, onError: reportError },
        );
      }}
      destroyOnHidden
    >
      {inUse ? (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Paragraph>
            {t('roles.delete_in_use', { count: role.user_count })}
          </Typography.Paragraph>
          <Select
            aria-label={t('roles.reassign_to')}
            placeholder={t('roles.reassign_to')}
            style={{ width: '100%' }}
            value={target}
            onChange={setTarget}
            options={(roles.data ?? [])
              .filter((other) => other.id !== role.id)
              .map((other) => ({ value: other.id, label: roleName(other, t) }))}
          />
        </Space>
      ) : (
        <Typography.Paragraph>{t('roles.delete_confirm')}</Typography.Paragraph>
      )}
    </Modal>
  );
}
