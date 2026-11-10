import { LockOutlined } from '@ant-design/icons';
import {
  Alert,
  App,
  Collapse,
  Drawer,
  Flex,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';

import {
  usePermissionCatalogue,
  useRole,
  useGroupRoleMutations,
  useRoleMutations,
  useRoles,
  useUnits,
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

import { groupByModule, roleName } from './roleName';

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
  /** With `role` null: a new custom role starting from this one's grants (REQ-ADM-017). */
  copyFrom?: RoleSummary;
  onClose: () => void;
  /** "Copy" on the open role (built-in ones included). */
  onCopy?: (role: RoleSummary) => void;
}

/**
 * Create or edit a custom role: name, description and a permission matrix grouped by module
 * (rows = permissions, one scope per permission). Permissions outside the plan are locked.
 * System roles open read-only. The server refuses grants beyond the editor's own permissions.
 */
export function RoleEditor({ role, copyFrom, onClose, onCopy }: RoleEditorProps) {
  const t = useLabel();
  const catalogue = usePermissionCatalogue(role !== undefined);
  const copying = role === null && copyFrom !== undefined;
  const detail = useRole(copying ? copyFrom.id : role?.id);
  const initial = role === null ? null : detail.data;
  const seed = copying ? detail.data : undefined;
  const ready =
    catalogue.data !== undefined && initial !== undefined && (!copying || seed !== undefined);
  return (
    <Drawer
      open={role !== undefined}
      onClose={onClose}
      width={760}
      destroyOnHidden
      title={
        copying
          ? t('roles.editor.copy', { name: roleName(copyFrom, t) })
          : role === null
            ? t('roles.editor.new')
            : role === undefined
              ? undefined
              : t('roles.editor.edit', { name: roleName(role, t) })
      }
    >
      {role !== undefined && ready ? (
        <RoleForm
          key={role?.id ?? `new-${copyFrom?.id ?? ''}`}
          role={role}
          initial={initial}
          seed={seed}
          catalogue={catalogue.data}
          onClose={onClose}
          onCopy={onCopy}
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
  seed,
  catalogue,
  onClose,
  onCopy,
}: {
  role: RoleSummary | null;
  initial: RoleDetail | null;
  /** A role to start from (a copy): its grants, and its name prefixed "Copy of". */
  seed?: RoleDetail;
  catalogue: PermissionInfo[];
  onClose: () => void;
  onCopy?: (role: RoleSummary) => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const { can } = useAccess();
  const { create, update, remove } = useRoleMutations();
  const [nameMissing, setNameMissing] = useState(false);
  const [name, setName] = useState(
    initial?.name ?? (seed === undefined ? '' : t('roles.copy_name', { name: roleName(seed, t) })),
  );
  const [description, setDescription] = useState(
    initial?.description ?? (seed?.is_system === true ? '' : (seed?.description ?? '')),
  );
  const [matrix, setMatrix] = useState<Matrix>(() =>
    Object.fromEntries(((initial ?? seed)?.permissions ?? []).map((g) => [g.permission, g])),
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
  const [permissionSearch, setPermissionSearch] = useState('');
  const [grantedOnly, setGrantedOnly] = useState(readOnly);
  const [openModules, setOpenModules] = useState<string[]>(() => modules.map(([m]) => m));
  const permissionQuery = permissionSearch.trim().toLocaleLowerCase();
  const shownModules = modules
    .map(([module, permissions]): [string, PermissionInfo[]] => [
      module,
      permissions.filter((permission) => {
        if (grantedOnly && matrix[permission.key] === undefined) return false;
        if (permissionQuery === '') return true;
        const text = `${t(`permission.${permission.key}`)} ${t(`permission.${permission.key}.description`)}`;
        return text.toLocaleLowerCase().includes(permissionQuery);
      }),
    ])
    .filter(([, permissions]) => permissions.length > 0);

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
        // D-153: what the built-in role is for and what it reaches; it is never changed or
        // deleted, so the way to adjust it is a copy.
        <Alert
          type="info"
          showIcon
          message={t(`role.${role.key}.description`)}
          description={
            <Space direction="vertical" size={4}>
              <span data-testid="role-default-scope">
                {t('roles.default_scope', { scope: t(`role.${role.key}.scope`) })}
              </span>
              <span>{t('roles.system_read_only')}</span>
            </Space>
          }
          data-testid="role-built-in"
        />
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
      {role !== null && onCopy !== undefined && can('roles.manage') && (
        <Flex justify="end">
          <WriteButton
            data-testid="copy-role"
            onClick={() => {
              onCopy(role);
            }}
          >
            {t('roles.copy_customise')}
          </WriteButton>
        </Flex>
      )}
      {role?.is_system !== true && (
        <Form layout="vertical">
          <Form.Item
            label={t('roles.name')}
            htmlFor="role-name"
            required
            validateStatus={nameMissing ? 'error' : undefined}
            help={nameMissing ? t('errors.field.required') : undefined}
          >
            <Input
              id="role-name"
              data-testid="role-name"
              value={name}
              count={lengthLimit(200)}
              disabled={readOnly}
              onChange={(event) => {
                setName(event.target.value);
                setNameMissing(false);
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
      {/* Find a right fast; a built-in role opens on what it grants (QA6S-PEO-06). */}
      <Flex gap={12} wrap align="center">
        <Input.Search
          allowClear
          aria-label={t('roles.search')}
          placeholder={t('roles.search')}
          value={permissionSearch}
          onChange={(event) => {
            setPermissionSearch(event.target.value);
          }}
          style={{ maxWidth: 320 }}
          data-testid="role-permission-search"
        />
        <Flex gap={8} align="center">
          <Switch
            checked={grantedOnly}
            onChange={setGrantedOnly}
            aria-labelledby="role-granted-only"
            data-testid="role-granted-only"
          />
          <Typography.Text id="role-granted-only">{t('roles.granted_only')}</Typography.Text>
        </Flex>
      </Flex>
      {shownModules.length === 0 && (
        <Typography.Text type="secondary">{t('roles.no_permission_found')}</Typography.Text>
      )}
      <Collapse
        // While searching or filtering, every module with a match is open; otherwise the
        // person's own open and closed modules (all open at first).
        activeKey={
          permissionQuery === '' && !grantedOnly ? openModules : shownModules.map(([m]) => m)
        }
        onChange={(keys) => {
          if (permissionQuery === '' && !grantedOnly) setOpenModules(([] as string[]).concat(keys));
        }}
        items={shownModules.map(([module, permissions]) => ({
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
      {initial !== null && can('groups.view') && (
        <RoleGroups
          roleId={initial.id}
          groupIds={initial.group_ids ?? []}
          onProblem={problem.show}
        />
      )}
      <FormProblem problem={problem} />
      {!readOnly && (
        // Delete on the start side, apart from Save (QA6S-PEO-08); Save is never disabled
        // without a reason: an empty name shows its error and takes the focus (PEO-07).
        <Flex justify="space-between" gap={8}>
          {role === null ? (
            <span />
          ) : (
            <WriteButton
              danger
              data-testid="delete-role"
              onClick={() => {
                setDeleting(true);
              }}
            >
              {t('roles.delete')}
            </WriteButton>
          )}
          <WriteButton
            type="primary"
            data-testid="save-role"
            loading={create.isPending || update.isPending}
            onClick={() => {
              if (role?.is_system !== true && name.trim() === '') {
                setNameMissing(true);
                document.getElementById('role-name')?.focus();
                return;
              }
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

/**
 * The support groups carrying the role (WP-042, REQ-ADM-015 AC2): their members hold it while
 * members. Adding or removing needs the same rights as giving the role to a person.
 */
function RoleGroups({
  roleId,
  groupIds,
  onProblem,
}: {
  roleId: string;
  groupIds: string[];
  onProblem: (error: unknown) => void;
}) {
  const t = useLabel();
  const { can } = useAccess();
  const groups = useUnits('groups');
  const { add, remove } = useGroupRoleMutations();
  const names = new Map((groups.data ?? []).map((g) => [g.id, g.name]));
  const editable = can('roles.manage');
  return (
    <Space direction="vertical" style={{ width: '100%' }} data-testid="role-groups">
      <Typography.Title level={4} style={{ margin: 0 }}>
        {t('roles.groups')}
      </Typography.Title>
      <Typography.Text type="secondary">{t('roles.groups_help')}</Typography.Text>
      <Flex wrap gap={6}>
        {groupIds.length === 0 && (
          <Typography.Text type="secondary">{t('roles.groups_none')}</Typography.Text>
        )}
        {groupIds.map((id) => (
          <Tag
            key={id}
            closable={editable}
            data-testid={`role-group-${id}`}
            onClose={(event) => {
              event.preventDefault();
              remove.mutate({ roleId, groupId: id }, { onError: onProblem });
            }}
          >
            {names.get(id) ?? '…'}
          </Tag>
        ))}
      </Flex>
      {editable && (
        <Select
          style={{ maxWidth: 320 }}
          placeholder={t('roles.groups_add')}
          aria-label={t('roles.groups_add')}
          value={null}
          loading={add.isPending}
          data-testid="role-groups-add"
          options={(groups.data ?? [])
            .filter((g) => !groupIds.includes(g.id))
            .map((g) => ({ value: g.id, label: g.name }))}
          onChange={(groupId: string) => {
            add.mutate({ roleId, groupId }, { onError: onProblem });
          }}
        />
      )}
    </Space>
  );
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
            // Read-only: the scope as text, not a disabled control (grey on grey, PEO-06).
            if (readOnly) {
              return (
                <Typography.Text
                  type={grant === undefined ? 'secondary' : undefined}
                  data-testid={`scope-${permission.key}`}
                >
                  {t(grant === undefined ? 'scope.none' : `scope.${grant.scope}`)}
                </Typography.Text>
              );
            }
            return (
              <Select<string>
                aria-label={t('roles.scope_of', { permission: t(`permission.${permission.key}`) })}
                data-testid={`scope-${permission.key}`}
                style={{ width: '100%' }}
                value={grant?.scope ?? NONE}
                disabled={!permission.entitled}
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
