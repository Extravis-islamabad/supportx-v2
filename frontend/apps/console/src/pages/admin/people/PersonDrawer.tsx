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
import { useEffect, useMemo, useState } from 'react';

import {
  ApiError,
  fetchUser,
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
  useConflictRetry,
  ConflictDialog,
  FormProblem,
  ToneTag,
  lengthLimit,
  markHandled,
  reportError,
  useAccess,
  useAppearance,
  useConflict,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

import { MemberAvailability } from '../../../MemberAvailability';
import { PersonSignInActions } from '../security/PersonSignInActions';
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

type Values = Omit<PersonFields, 'request_visibility'> & {
  // '' is the "organisation's rule" option (sent as null).
  request_visibility?: PersonFields['request_visibility'] | '';
  user_type?: UserDetail['user_type'];
  can_sign_in?: boolean;
};

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
    // '' stands for "the organisation's rule" (a select option cannot be null; QA BUG-07).
    request_visibility: user.request_visibility ?? '',
  };
}

/** '' (an emptied text, the "organisation's rule" option) is sent as null. */
function normal(value: unknown): unknown {
  return typeof value === 'string' && value.trim() === '' ? null : (value ?? null);
}

/** Only what differs from the record the editor started from. */
function changes(values: Values, base: Values): PersonFields {
  const out: PersonFields & Record<string, unknown> = {};
  for (const [key, raw] of Object.entries(values)) {
    if (key === 'user_type' || key === 'can_sign_in') continue;
    const value = normal(raw);
    if (value !== normal((base as Record<string, unknown>)[key])) out[key] = value;
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
  // Versions this drawer saved itself (type, sign-in, status, the form): not someone else's
  // change, so they never make the open form stale (QA WP-021 BUG-03).
  const [own] = useState(() => new Set<number>());
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
                  <PersonStatus user={user} own={own} />
                  <PersonForm key={user.id} user={user} own={own} />
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
  own,
}: {
  user: UserDetail | undefined;
  onSaved?: (user: UserDetail) => void;
  own?: Set<number>;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const { create, update } = usePersonChange();
  const queryClient = useQueryClient();
  // The record this form started from: its values and version (QA WP-026 BUG-01).
  const [base, setBase] = useState(() => ({ values: snapshot(user), version: user?.version }));
  const [conflict, setConflict] = useState<unknown>();
  const [problems, setProblems] = useState<Record<string, string>>({});
  // A refusal with no field to point at (a rule, a limit) is shown above Save (QA WP-029 BUG-02).
  const problem = useFormProblem();
  const [form] = Form.useForm<Values>();
  const [dirty, setDirty] = useState(false);
  // The record moved on (adjusted while rendering, as for useDraft): with no unsaved edits the
  // form simply shows the latest; this drawer's own saves never count as someone else's.
  if (user !== undefined && base.version !== undefined && user.version !== base.version) {
    if (!dirty) {
      setBase({ values: snapshot(user), version: user.version });
    } else if (own?.has(user.version) === true) {
      setBase({ values: base.values, version: user.version });
    }
  }
  const stale = user !== undefined && base.version !== undefined && user.version !== base.version;
  // A new base record (saved, reloaded, or followed while clean) is what the fields show; the
  // form instance keeps its values across renders, so they are set, not just initialised.
  useEffect(() => {
    form.setFieldsValue(base.values);
  }, [form, base.values]);
  const { locale } = useAppearance();
  const when =
    user === undefined
      ? ''
      : new Intl.DateTimeFormat(locale, { timeStyle: 'short' }).format(new Date(user.updated_at));

  const showProblems = (error: unknown): boolean => {
    if (!(error instanceof ApiError) || error.status !== 422 || error.fieldErrors.length === 0) {
      return false;
    }
    markHandled(error);
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
    problem.clear();
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
            if (!showProblems(error)) problem.show(error);
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
          own?.add(saved.version);
          void message.success(t('common.saved'));
          // The form shows what was stored, the notice goes (QA WP-021 BUG-03).
          setBase({ values: snapshot(saved), version: saved.version });
          setDirty(false);
        },
        onError: (error) => {
          if (error instanceof ApiError && error.isConflict) {
            // Fetch the latest now: "keep mine" must save on top of it, live update or not.
            void queryClient.invalidateQueries({ queryKey: queryKeys.users.detail(user.id) });
            setConflict(error);
            return;
          }
          if (!showProblems(error)) problem.show(error);
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
        form={form}
        layout="vertical"
        initialValues={base.values}
        onFinish={(values) => {
          save(values);
        }}
        onValuesChange={(changed) => {
          setDirty(true);
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
            <Input
              dir="ltr"
              // Inline: Ant Design's RTL stylesheet sets `direction: rtl` on inputs, which
              // beats the attribute and showed numbers reversed in Arabic (QA BUG-05).
              styles={{ input: { direction: 'ltr' } }}
              count={lengthLimit(LENGTHS.phone ?? 50)}
            />
          </Form.Item>
          <Form.Item
            name="mobile"
            label={t('people.field.mobile')}
            style={{ flex: 1, minWidth: 160 }}
            {...help('mobile')}
          >
            <Input
              dir="ltr"
              styles={{ input: { direction: 'ltr' } }}
              count={lengthLimit(LENGTHS.mobile ?? 50)}
            />
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
              data-testid="person-request-visibility"
              options={[
                { value: '', label: t('people.visibility.tenant_rule') },
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
        <FormProblem problem={problem} />
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
            setDirty(false);
          }
        }}
        onKeepMine={() => {
          setConflict(undefined);
          if (user === undefined) return;
          // Keep my edits on top of the latest version: only the fields I changed are sent, the
          // others keep what was saved meanwhile; then the form shows the stored record. The
          // latest is read first, so a quick click never saves on the old version again.
          const mine = form.getFieldsValue();
          void queryClient
            .query({
              queryKey: queryKeys.users.detail(user.id),
              queryFn: () => fetchUser(user.id),
              staleTime: 0,
            })
            .then((latest) => {
              save(mine, latest.version);
            })
            .catch(reportError);
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
  const form = Form.useFormInstance<Values>();
  const sites = useStructure('sites', can('sites.view'));
  const departments = useStructure('departments', can('departments.view'));
  // D-096: a chosen department suggests its site, only while the person has no site.
  const suggestSite = (departmentId: string | undefined) => {
    if (departmentId === undefined || normal(form.getFieldValue('site_id')) !== null) return;
    const siteId = departments.data?.find((d) => d.id === departmentId)?.site_id;
    if (siteId != null) form.setFieldValue('site_id', siteId);
  };
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
            onChange={(value: string | undefined) => {
              suggestSite(value);
            }}
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
function PersonStatus({ user, own }: { user: UserDetail; own: Set<number> }) {
  const t = useLabel();
  const { can } = useAccess();
  const { modal } = App.useApp();
  const { setType, setSignIn, deactivate } = usePersonChange();
  const [reactivating, setReactivating] = useState(false);
  // Changed by someone after it was shown (409): the shared dialog says who, when and what
  // (QA WP-029 BUG-05); "Keep my changes" makes the change again on the saved version.
  const conflict = useConflict();
  const [retry, setRetry] = useState<(version: number) => void>();
  const failed = (again: (version: number) => void) => (error: unknown) => {
    if (conflict.take(error)) {
      setRetry(() => again);
      return;
    }
    reportError(error);
  };
  const saved = (next: UserDetail) => own.add(next.version);
  const changeType = (userType: UserDetail['user_type'], version = user.version) => {
    setType.mutate(
      { id: user.id, version, userType },
      {
        onError: failed((at) => {
          changeType(userType, at);
        }),
        onSuccess: saved,
      },
    );
  };
  const changeSignIn = (allowed: boolean, version = user.version) => {
    setSignIn.mutate(
      { id: user.id, version, allowed },
      {
        onError: failed((at) => {
          changeSignIn(allowed, at);
        }),
        onSuccess: saved,
      },
    );
  };
  const deactivateNow = (version = user.version) => {
    deactivate.mutate(
      { id: user.id, version },
      {
        onError: failed((at) => {
          deactivateNow(at);
        }),
        onSuccess: saved,
      },
    );
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
            const change = () => {
              changeType(value);
            };
            if (value !== 'technician') {
              change();
              return;
            }
            // A technician takes a licence seat: ask first (QA WP-021 C5).
            void modal.confirm({
              title: t('people.make_technician.title', { name: user.display_name }),
              content: t('people.make_technician.explain'),
              okText: t('people.make_technician'),
              cancelText: t('actions.cancel'),
              onOk: change,
            });
          }}
        />
      </Flex>
      <Flex gap={16} wrap align="center">
        <Typography.Text id="person-sign-in-label">{t('people.field.can_sign_in')}</Typography.Text>
        <Switch
          aria-labelledby="person-sign-in-label"
          data-testid="person-sign-in"
          checked={user.can_sign_in}
          disabled={busy}
          onChange={(allowed) => {
            changeSignIn(allowed);
          }}
        />
      </Flex>
      {user.user_type === 'technician' && (
        <Flex gap={16} wrap align="start">
          <Typography.Text>{t('availability.member_label')}</Typography.Text>
          {/* An admin sets a sick technician Away: no auto-assigned work (QA WP-029 follow-up). */}
          <MemberAvailability userId={user.id} canSet={can('users.manage')} showHistory />
        </Flex>
      )}
      <PersonSignInActions user={user} />
      {user.status === 'active' ? (
        <Popconfirm
          title={t('people.deactivate.confirm', { name: user.display_name })}
          description={t('people.deactivate.explain')}
          okText={t('people.deactivate')}
          cancelText={t('actions.cancel')}
          onConfirm={() => {
            deactivateNow();
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
        own={own}
        open={reactivating}
        onClose={() => {
          setReactivating(false);
        }}
      />
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={(field) => t(personFieldKey(field))}
        onReload={() => {
          conflict.clear();
          setRetry(undefined);
        }}
        onKeepMine={() => {
          conflict.clear();
          if (retry !== undefined) retry(conflict.latestVersion ?? user.version);
          setRetry(undefined);
        }}
      />
    </Flex>
  );
}

/** Reactivation lists what the person still holds; only the ticked roles and groups stay. */
function ReactivateDialog({
  user,
  own,
  open,
  onClose,
}: {
  user: UserDetail;
  own: Set<number>;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { can } = useAccess();
  const held = useReactivation(open ? user.id : undefined);
  const roles = useRoles(open && can('roles.view'));
  const groups = useUnits('groups', open && can('groups.view'));
  const { reactivate } = usePersonChange();
  const problem = useFormProblem();
  // Changed by someone after it was shown (409): the shared dialog (QA WP-029 BUG-05).
  const conflict = useConflictRetry();
  const [keepRoles, setKeepRoles] = useState<string[] | null>(null);
  const [keepGroups, setKeepGroups] = useState<string[] | null>(null);
  const roleIds = keepRoles ?? held.data?.role_ids ?? [];
  const groupIds = keepGroups ?? held.data?.group_ids ?? [];
  const send = (version: number) => {
    problem.clear();
    reactivate.mutate(
      { id: user.id, version, keepRoleIds: roleIds, keepGroupIds: groupIds },
      {
        onSuccess: (saved) => {
          own.add(saved.version);
          onClose();
        },
        onError: (error) => {
          if (!conflict.take(error, send)) problem.show(error);
        },
      },
    );
  };
  return (
    <Modal
      open={open}
      title={t('people.reactivate.title', { name: user.display_name })}
      okText={t('people.reactivate')}
      cancelText={t('actions.cancel')}
      onCancel={() => {
        problem.clear();
        onClose();
      }}
      okButtonProps={{ 'data-testid': 'reactivate-confirm', loading: reactivate.isPending }}
      destroyOnHidden
      onOk={() => {
        send(user.version);
      }}
    >
      {held.data === undefined ? (
        <Spin />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }}>
          <FormProblem problem={problem} />
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
      <ConflictDialog {...conflict.dialog} fieldLabel={(field) => t(personFieldKey(field))} />
    </Modal>
  );
}
