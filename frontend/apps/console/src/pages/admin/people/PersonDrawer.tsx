import {
  Alert,
  App,
  Button,
  Checkbox,
  Drawer,
  Flex,
  Form,
  Input,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Spin,
  Switch,
  Tabs,
  Typography,
} from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import {
  ApiError,
  queryKeys,
  usePersonChange,
  useReactivation,
  useRoles,
  useStructure,
  useUnits,
  useUser,
  useUsers,
  type PersonFields,
  type UserDetail,
} from '@supportx/api-client';
import { refreshRecord, useRecordChannel } from '@supportx/realtime';
import {
  ConflictDialog,
  ToneTag,
  lengthLimit,
  reportError,
  useAccess,
  useAppearance,
  useLabel,
} from '@supportx/ui';

import { UserAccessPanel } from '../UserAccessDrawer';
import { roleName } from '../roleName';
import { personFieldKey } from './fields';

/** Longest text per field: refused with the limit by the server, counted here (D-091). */
const LENGTHS: Record<string, number> = {
  first_name: 100,
  last_name: 100,
  display_name: 200,
  email: 254,
  employee_id: 50,
  job_title: 200,
  phone: 50,
  mobile: 50,
  description: 5000,
};
const LOCALES = ['en', 'ar', 'ur'] as const;

type Values = PersonFields & { user_type?: UserDetail['user_type']; can_sign_in?: boolean };

function snapshot(user: UserDetail | undefined): Values {
  if (user === undefined) return { user_type: 'requester', can_sign_in: true, vip: false };
  return {
    first_name: user.first_name,
    last_name: user.last_name,
    display_name: user.name_custom ? user.display_name : null,
    email: user.email,
    employee_id: user.employee_id,
    job_title: user.job_title,
    description: user.description ?? null,
    phone: user.phone,
    mobile: user.mobile,
    vip: user.vip,
    site_id: user.site_id,
    department_id: user.department_id,
    manager_id: user.manager_id,
    locale: user.locale,
    time_zone: user.time_zone,
    request_visibility: user.request_visibility,
  };
}

/** Only what differs from the record the editor started from; '' becomes null. */
function changes(values: Values, base: Values): PersonFields {
  const out: Record<string, unknown> = {};
  for (const [key, raw] of Object.entries(values)) {
    if (key === 'user_type' || key === 'can_sign_in') continue;
    const value = typeof raw === 'string' && raw.trim() === '' ? null : raw;
    const before = (base as Record<string, unknown>)[key] ?? null;
    if ((value ?? null) !== before) out[key] = value ?? null;
  }
  return out;
}

export interface PersonDrawerProps {
  /** The person to edit; `'new'` adds one; undefined: closed. */
  userId: string | undefined;
  onClose: () => void;
  onCreated?: (user: UserDetail) => void;
}

/**
 * Admin › People: one person's record, type, sign-in and status (WP-021, REQ-ADM-002..005).
 *
 * The editor keeps the version it opened (QA WP-026 BUG-01): a save made elsewhere meanwhile is
 * said at once, and saving then shows the conflict dialog. Never a silent overwrite.
 */
export function PersonDrawer({ userId, onClose, onCreated }: PersonDrawerProps) {
  const t = useLabel();
  const creating = userId === 'new';
  const record = useUser(userId === undefined || creating ? undefined : userId);
  const user = creating ? undefined : record.data;
  const queryClient = useQueryClient();
  useRecordChannel('users', creating ? undefined : userId, (message) => {
    if (userId !== undefined) refreshRecord(queryClient, queryKeys.users.detail(userId), message);
  });
  const title = creating
    ? t('people.add')
    : user === undefined
      ? undefined
      : t('people.title_person', { name: user.display_name });
  return (
    <Drawer
      open={userId !== undefined}
      onClose={onClose}
      width={560}
      title={title}
      destroyOnHidden
      data-testid="person-drawer"
    >
      {userId === undefined || (!creating && user === undefined) ? (
        <Spin />
      ) : creating ? (
        <PersonForm
          key="new"
          user={undefined}
          onSaved={(saved) => {
            onCreated?.(saved);
            onClose();
          }}
        />
      ) : user === undefined ? null : (
        <Tabs
          items={[
            {
              key: 'details',
              label: t('people.tab.details'),
              children: (
                <Space direction="vertical" size="large" style={{ width: '100%' }}>
                  <PersonStatus user={user} />
                  <PersonForm key={user.id} user={user} />
                </Space>
              ),
            },
            {
              key: 'access',
              label: t('people.tab.access'),
              children: <UserAccessPanel user={user} />,
            },
          ]}
        />
      )}
    </Drawer>
  );
}

function PersonForm({
  user,
  onSaved,
}: {
  user: UserDetail | undefined;
  onSaved?: (user: UserDetail) => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const { create, update } = usePersonChange();
  // The record this form started from: its values and version (QA WP-026 BUG-01).
  const [base, setBase] = useState(() => ({ values: snapshot(user), version: user?.version }));
  const [formKey, setFormKey] = useState(0);
  const [conflict, setConflict] = useState<unknown>();
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [form] = Form.useForm<Values>();
  const stale = user !== undefined && base.version !== undefined && user.version !== base.version;
  const { locale } = useAppearance();
  const when =
    user === undefined
      ? ''
      : new Intl.DateTimeFormat(locale, { timeStyle: 'short' }).format(new Date(user.updated_at));

  const showProblems = (error: unknown): boolean => {
    if (!(error instanceof ApiError) || error.status !== 422) return false;
    setProblems(
      Object.fromEntries(
        error.fieldErrors.map((f) => [
          f.field.replace(/^body\./, ''),
          t(f.message_key, f.params ?? {}),
        ]),
      ),
    );
    return true;
  };

  const save = (values: Values, version = base.version) => {
    setProblems({});
    if (user === undefined) {
      const body = { ...changes(values, {}), first_name: values.first_name ?? '' };
      create.mutate(
        {
          ...body,
          user_type: values.user_type ?? 'requester',
          can_sign_in: values.can_sign_in ?? true,
        },
        {
          onSuccess: (saved) => {
            void message.success(t('people.added', { name: saved.display_name }));
            onSaved?.(saved);
          },
          onError: (error) => {
            if (!showProblems(error)) reportError(error);
          },
        },
      );
      return;
    }
    const body = changes(values, base.values);
    if (Object.keys(body).length === 0 && version === user.version) return;
    update.mutate(
      { id: user.id, version: version ?? user.version, body },
      {
        onSuccess: (saved) => {
          void message.success(t('settings.saved'));
          setBase({ values: snapshot(saved), version: saved.version });
        },
        onError: (error) => {
          if (error instanceof ApiError && error.isConflict) {
            setConflict(error);
            return;
          }
          if (!showProblems(error)) reportError(error);
        },
      },
    );
  };

  const help = (name: string) =>
    problems[name] === undefined ? {} : { validateStatus: 'error' as const, help: problems[name] };

  return (
    <>
      {stale && (
        <Alert
          type="warning"
          showIcon
          data-testid="person-stale"
          message={t('people.changed_elsewhere', { time: when })}
          style={{ marginBottom: 16 }}
        />
      )}
      <Form<Values>
        key={formKey}
        form={form}
        layout="vertical"
        initialValues={base.values}
        onFinish={(values) => {
          save(values);
        }}
        onValuesChange={(changed) => {
          const cleared = Object.keys(changed as Record<string, unknown>);
          if (cleared.some((name) => problems[name] !== undefined)) {
            setProblems((all) =>
              Object.fromEntries(Object.entries(all).filter(([k]) => !cleared.includes(k))),
            );
          }
        }}
        data-testid="person-form"
      >
        <Flex gap={12} wrap>
          <Form.Item
            name="first_name"
            label={t('people.field.first_name')}
            required
            style={{ flex: 1, minWidth: 200 }}
            {...help('first_name')}
          >
            <Input count={lengthLimit(LENGTHS.first_name ?? 100)} data-testid="person-first-name" />
          </Form.Item>
          <Form.Item
            name="last_name"
            label={t('people.field.last_name')}
            style={{ flex: 1, minWidth: 200 }}
            {...help('last_name')}
          >
            <Input count={lengthLimit(LENGTHS.last_name ?? 100)} data-testid="person-last-name" />
          </Form.Item>
        </Flex>
        <Form.Item
          name="display_name"
          label={t('people.field.display_name')}
          extra={t('people.field.display_name.help')}
          {...help('display_name')}
        >
          <Input count={lengthLimit(LENGTHS.display_name ?? 200)} />
        </Form.Item>
        <Form.Item name="email" label={t('people.field.email')} {...help('email')}>
          <Input
            type="email"
            count={lengthLimit(LENGTHS.email ?? 254)}
            data-testid="person-email"
          />
        </Form.Item>
        {user === undefined && (
          <Flex gap={24} wrap>
            <Form.Item name="user_type" label={t('people.field.user_type')}>
              <Segmented
                options={(['requester', 'technician'] as const).map((value) => ({
                  value,
                  label: t(`user_type.${value}`),
                }))}
              />
            </Form.Item>
            <Form.Item
              name="can_sign_in"
              label={t('people.field.can_sign_in')}
              valuePropName="checked"
              extra={t('people.field.can_sign_in.help')}
            >
              <Switch data-testid="person-can-sign-in" />
            </Form.Item>
          </Flex>
        )}
        <Flex gap={12} wrap>
          <Form.Item
            name="employee_id"
            label={t('people.field.employee_id')}
            style={{ flex: 1, minWidth: 160 }}
            {...help('employee_id')}
          >
            <Input count={lengthLimit(LENGTHS.employee_id ?? 50)} />
          </Form.Item>
          <Form.Item
            name="job_title"
            label={t('people.field.job_title')}
            style={{ flex: 2, minWidth: 200 }}
            {...help('job_title')}
          >
            <Input count={lengthLimit(LENGTHS.job_title ?? 200)} />
          </Form.Item>
        </Flex>
        <Flex gap={12} wrap>
          <Form.Item
            name="phone"
            label={t('people.field.phone')}
            style={{ flex: 1, minWidth: 160 }}
            {...help('phone')}
          >
            <Input dir="ltr" count={lengthLimit(LENGTHS.phone ?? 50)} />
          </Form.Item>
          <Form.Item
            name="mobile"
            label={t('people.field.mobile')}
            style={{ flex: 1, minWidth: 160 }}
            {...help('mobile')}
          >
            <Input dir="ltr" count={lengthLimit(LENGTHS.mobile ?? 50)} />
          </Form.Item>
        </Flex>
        <PlacementFields user={user} help={help} />
        <Flex gap={24} wrap>
          <Form.Item name="vip" label={t('people.field.vip')} valuePropName="checked">
            <Switch data-testid="person-vip" />
          </Form.Item>
          <Form.Item name="locale" label={t('people.field.locale')} style={{ minWidth: 160 }}>
            <Select
              allowClear
              options={LOCALES.map((value) => ({ value, label: t(`locale.${value}`) }))}
            />
          </Form.Item>
          <Form.Item
            name="request_visibility"
            label={t('people.field.request_visibility')}
            style={{ minWidth: 220 }}
          >
            <Select
              options={[
                { value: null, label: t('people.visibility.tenant_rule') },
                { value: 'site', label: t('people.visibility.site') },
              ]}
            />
          </Form.Item>
        </Flex>
        <Form.Item
          name="description"
          label={t('people.field.description')}
          {...help('description')}
        >
          <Input.TextArea rows={3} count={lengthLimit(LENGTHS.description ?? 5000)} />
        </Form.Item>
        <Button
          type="primary"
          htmlType="submit"
          loading={create.isPending || update.isPending}
          data-testid="person-save"
        >
          {user === undefined ? t('people.add') : t('actions.save')}
        </Button>
      </Form>
      <ConflictDialog
        open={conflict !== undefined}
        error={conflict}
        fieldLabel={(field) => t(personFieldKey(field))}
        onReload={() => {
          setConflict(undefined);
          if (user !== undefined) {
            setBase({ values: snapshot(user), version: user.version });
            setFormKey((key) => key + 1);
          }
        }}
        onKeepMine={() => {
          setConflict(undefined);
          if (user === undefined) return;
          // Keep my edits on top of the latest version, then save again.
          const mine = form.getFieldsValue();
          setBase({ values: snapshot(user), version: user.version });
          save(mine, user.version);
        }}
      />
    </>
  );
}

/** Site, department and manager pickers; inactive ones only when already set. */
function PlacementFields({
  user,
  help,
}: {
  user: UserDetail | undefined;
  help: (name: string) => object;
}) {
  const t = useLabel();
  const { can } = useAccess();
  const sites = useStructure('sites', can('sites.view'));
  const departments = useStructure('departments', can('departments.view'));
  const [managerSearch, setManagerSearch] = useState('');
  const managers = useUsers({ q: managerSearch, limit: 20 }, can('users.view'));
  const managerOptions = useMemo(() => {
    const found = managers.data?.pages.flatMap((page) => page.items) ?? [];
    return found
      .filter((person) => person.id !== user?.id)
      .map((person) => ({
        value: person.id,
        label:
          person.email === null ? person.display_name : `${person.display_name} (${person.email})`,
      }));
  }, [managers.data, user?.id]);
  const usable = <T extends { id: string; disabled: boolean }>(
    rows: T[] | undefined,
    kept?: string | null,
  ) => (rows ?? []).filter((row) => !row.disabled || row.id === kept);
  return (
    <>
      <Flex gap={12} wrap>
        <Form.Item
          name="site_id"
          label={t('people.field.site')}
          style={{ flex: 1, minWidth: 200 }}
          {...help('site_id')}
        >
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            data-testid="person-site"
            options={usable(sites.data, user?.site_id).map((site) => ({
              value: site.id,
              label: site.disabled ? `${site.name} ${t('people.inactive_suffix')}` : site.name,
            }))}
          />
        </Form.Item>
        <Form.Item
          name="department_id"
          label={t('people.field.department')}
          style={{ flex: 1, minWidth: 200 }}
          {...help('department_id')}
        >
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            data-testid="person-department"
            options={usable(departments.data, user?.department_id).map((department) => ({
              value: department.id,
              label: department.disabled
                ? `${department.name} ${t('people.inactive_suffix')}`
                : department.name,
            }))}
          />
        </Form.Item>
      </Flex>
      <Form.Item name="manager_id" label={t('people.field.manager')} {...help('manager_id')}>
        <Select
          allowClear
          showSearch
          filterOption={false}
          onSearch={setManagerSearch}
          data-testid="person-manager"
          options={
            user?.manager_id != null && !managerOptions.some((o) => o.value === user.manager_id)
              ? [{ value: user.manager_id, label: t('people.current_manager') }, ...managerOptions]
              : managerOptions
          }
        />
      </Form.Item>
    </>
  );
}

/** Type, sign-in and active/deactivated, each its own audited action. */
function PersonStatus({ user }: { user: UserDetail }) {
  const t = useLabel();
  const { message } = App.useApp();
  const { setType, setSignIn, deactivate } = usePersonChange();
  const [reactivating, setReactivating] = useState(false);
  const onError = (error: unknown) => {
    if (error instanceof ApiError && error.isConflict) {
      void message.warning(t('people.changed_reload'));
      return;
    }
    reportError(error);
  };
  const busy = setType.isPending || setSignIn.isPending || deactivate.isPending;
  return (
    <Flex vertical gap={12} data-testid="person-status">
      <Flex gap={8} wrap align="center">
        {user.status === 'disabled' && (
          <ToneTag tone="warning" testId="person-deactivated">
            {t('user_status.disabled')}
          </ToneTag>
        )}
        {!user.can_sign_in && <ToneTag tone="default">{t('people.contact')}</ToneTag>}
        {user.vip && <ToneTag tone="purple">{t('people.vip')}</ToneTag>}
        {user.can_sign_in && !user.signed_in_before && (
          <ToneTag tone="info">{t('people.not_signed_in_yet')}</ToneTag>
        )}
      </Flex>
      <Flex gap={16} wrap align="center">
        <Typography.Text>{t('people.field.user_type')}</Typography.Text>
        <Segmented
          data-testid="person-type"
          disabled={busy}
          value={user.user_type}
          options={(['requester', 'technician'] as const).map((value) => ({
            value,
            label: t(`user_type.${value}`),
          }))}
          onChange={(value) => {
            setType.mutate({ id: user.id, version: user.version, userType: value }, { onError });
          }}
        />
      </Flex>
      <Flex gap={16} wrap align="center">
        <Typography.Text>{t('people.field.can_sign_in')}</Typography.Text>
        <Switch
          data-testid="person-sign-in"
          checked={user.can_sign_in}
          disabled={busy}
          onChange={(allowed) => {
            setSignIn.mutate({ id: user.id, version: user.version, allowed }, { onError });
          }}
        />
      </Flex>
      {user.status === 'active' ? (
        <Popconfirm
          title={t('people.deactivate.confirm', { name: user.display_name })}
          description={t('people.deactivate.explain')}
          okText={t('people.deactivate')}
          cancelText={t('actions.cancel')}
          onConfirm={() => {
            deactivate.mutate({ id: user.id, version: user.version }, { onError });
          }}
        >
          <Button danger loading={deactivate.isPending} data-testid="person-deactivate">
            {t('people.deactivate')}
          </Button>
        </Popconfirm>
      ) : (
        <Button
          type="primary"
          onClick={() => {
            setReactivating(true);
          }}
          data-testid="person-reactivate"
        >
          {t('people.reactivate')}
        </Button>
      )}
      <ReactivateDialog
        user={user}
        open={reactivating}
        onClose={() => {
          setReactivating(false);
        }}
      />
    </Flex>
  );
}

/** Reactivation lists what the person still holds; only the ticked roles and groups stay. */
function ReactivateDialog({
  user,
  open,
  onClose,
}: {
  user: UserDetail;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { can } = useAccess();
  const held = useReactivation(open ? user.id : undefined);
  const roles = useRoles(open && can('roles.view'));
  const groups = useUnits('groups', open && can('groups.view'));
  const { reactivate } = usePersonChange();
  const [keepRoles, setKeepRoles] = useState<string[] | null>(null);
  const [keepGroups, setKeepGroups] = useState<string[] | null>(null);
  const roleIds = keepRoles ?? held.data?.role_ids ?? [];
  const groupIds = keepGroups ?? held.data?.group_ids ?? [];
  return (
    <Modal
      open={open}
      title={t('people.reactivate.title', { name: user.display_name })}
      okText={t('people.reactivate')}
      cancelText={t('actions.cancel')}
      onCancel={onClose}
      okButtonProps={{ 'data-testid': 'reactivate-confirm', loading: reactivate.isPending }}
      destroyOnHidden
      onOk={() => {
        reactivate.mutate(
          { id: user.id, version: user.version, keepRoleIds: roleIds, keepGroupIds: groupIds },
          {
            onSuccess: onClose,
            onError: (error) => {
              reportError(error);
            },
          },
        );
      }}
    >
      {held.data === undefined ? (
        <Spin />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Paragraph>{t('people.reactivate.explain')}</Typography.Paragraph>
          <Typography.Title level={5}>{t('access.roles')}</Typography.Title>
          {held.data.role_ids.length === 0 ? (
            <Typography.Text type="secondary">{t('access.none')}</Typography.Text>
          ) : (
            <Checkbox.Group
              value={roleIds}
              onChange={(next) => {
                setKeepRoles(next);
              }}
              options={held.data.role_ids.map((id) => {
                const role = roles.data?.find((r) => r.id === id);
                return { value: id, label: role === undefined ? '…' : roleName(role, t) };
              })}
            />
          )}
          <Typography.Title level={5}>{t('access.groups')}</Typography.Title>
          {held.data.group_ids.length === 0 ? (
            <Typography.Text type="secondary">{t('access.none')}</Typography.Text>
          ) : (
            <Checkbox.Group
              value={groupIds}
              onChange={(next) => {
                setKeepGroups(next);
              }}
              options={held.data.group_ids.map((id) => ({
                value: id,
                label: groups.data?.find((g) => g.id === id)?.name ?? '…',
              }))}
            />
          )}
        </Space>
      )}
    </Modal>
  );
}
