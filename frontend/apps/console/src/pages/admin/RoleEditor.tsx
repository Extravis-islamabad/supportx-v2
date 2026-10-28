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
import {
  ConflictDialog,
  FormProblem,
  useAccess,
  useConflict,
  useFormProblem,
  useLabel,
  WriteButton,
  lengthLimit,
} from '@supportx/ui';

import { roleName } from './roleName';

type Matrix = Record<string, RoleGrant | undefined>;
const NONE = 'none';
// What a person edits of a role, by the names the editor gives them (QA WP-029 BUG-05).
const ROLE_PARTS: Record<string, string> = {
  name: 'roles.name',
  description: 'roles.description',
  permissions: 'roles.permissions',
};
const roleView = (role: RoleDetail | null | undefined) =>
  role == null
    ? undefined
    : { name: role.name, description: role.description, permissions: role.permissions };

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
  // A refused save (a rule, a limit) is shown above Save (QA WP-029 BUG-02).
  const problem = useFormProblem();
  // The version this form was filled from: the save sends it, so a role saved elsewhere meanwhile
  // is refused, never overwritten (QA WP-026 BUG-01); the change is announced at once.
  const [base, setBase] = useState(initial?.version ?? 0);
  // The role as this form was filled from it, and a save another admin beat (409): the shared
  // dialog names who, when and what (QA WP-029 BUG-05).
  const [opened, setOpened] = useState(initial);
  const conflict = useConflict();
  const stale = initial !== null && initial.version !== base;
  const readOnly = role?.is_system === true || !can('roles.manage');
  const modules = useMemo(() => groupByModule(catalogue), [catalogue]);

  const save = (version = base) => {
    const permissions = Object.values(matrix).filter((g): g is RoleGrant => g !== undefined);
    const body = { name, description: description === '' ? null : description, permissions };
    const done = () => {
      void message.success(t('roles.saved'));
      onClose();
    };
    problem.clear();
    if (initial === null) {
      create.mutate(body, { onSuccess: done, onError: problem.show });
    } else {
      update.mutate(
        { id: initial.id, version, body },
        {
          onSuccess: done,
          onError: (error) => {
            if (conflict.take(error)) return;
            problem.show(error);
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
      <FormProblem problem={problem} />
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
            onClick={() => {
              save();
            }}
          >
            {t('actions.save')}
          </WriteButton>
        </Flex>
      )}
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={(field) => t(ROLE_PARTS[field] ?? 'roles.permissions')}
        opened={roleView(opened)}
        latest={roleView(initial)}
        onReload={() => {
          conflict.clear();
          if (initial === null) return;
          setName(initial.name);
          setDescription(initial.description ?? '');
          setMatrix(Object.fromEntries(initial.permissions.map((g) => [g.permission, g])));
          setBase(initial.version);
          setOpened(initial);
        }}
        onKeepMine={() => {
          conflict.clear();
          const latest = conflict.latestVersion ?? initial?.version ?? base;
          setBase(latest);
          setOpened(initial);
          save(latest);
        }}
      />
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
  // A refused delete is shown in this dialog (QA WP-029 BUG-02).
  const problem = useFormProblem();
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
      onCancel={() => {
        problem.clear();
        onCancel();
      }}
      onOk={() => {
        problem.clear();
        remove.mutate(
          { id: role.id, version, reassignTo: target },
          { onSuccess: onDeleted, onError: problem.show },
        );
      }}
      destroyOnHidden
    >
      <FormProblem problem={problem} />
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
