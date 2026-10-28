import { PlusOutlined } from '@ant-design/icons';
import {
  Alert,
  App,
  Button,
  Drawer,
  Flex,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Divider,
  Typography,
} from 'antd';
import { useMemo, useState, type ReactNode } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router';

import {
  ApiError,
  useStructure,
  useStructureChange,
  useUsers,
  type StructureKind,
  useSession,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import {
  ConflictDialog,
  FormProblem,
  NoAccess,
  ToneTag,
  lengthLimit,
  markHandled,
  reportError,
  useAccess,
  useConflict,
  useFormProblem,
  useLabel,
  useLicence,
} from '@supportx/ui';

import { GroupMembersAvailability } from '../../../GroupMembersAvailability';

type Row = {
  id: string;
  version: number;
  disabled: boolean;
  name?: string;
  is_default?: boolean;
} & Record<string, unknown>;

type FieldKind =
  'text' | 'textarea' | 'language' | 'timezone' | 'site' | 'sites' | 'person' | 'parent' | 'desk';

interface FieldSpec {
  name: string;
  kind: FieldKind;
  max?: number;
  required?: boolean;
  /** Only when adding (a desk's code never changes). */
  createOnly?: boolean;
}

const FIELDS: Record<StructureKind, FieldSpec[]> = {
  sites: [
    { name: 'name', kind: 'text', max: 200, required: true },
    { name: 'description', kind: 'textarea', max: 2000 },
    { name: 'region', kind: 'text', max: 100 },
    { name: 'time_zone', kind: 'timezone' },
    { name: 'default_language', kind: 'language' },
    { name: 'address', kind: 'textarea', max: 1000 },
    { name: 'phone', kind: 'text', max: 50 },
    { name: 'email', kind: 'text', max: 320 },
  ],
  groups: [
    { name: 'name', kind: 'text', max: 200, required: true },
    { name: 'description', kind: 'textarea', max: 2000 },
    { name: 'lead_id', kind: 'person' },
    { name: 'site_ids', kind: 'sites' },
    { name: 'email', kind: 'text', max: 320 },
    { name: 'sender_name', kind: 'text', max: 200 },
    { name: 'desk_id', kind: 'desk' },
  ],
  departments: [
    { name: 'name', kind: 'text', max: 200, required: true },
    { name: 'code', kind: 'text', max: 50 },
    { name: 'site_id', kind: 'site' },
    { name: 'head_id', kind: 'person' },
    { name: 'parent_id', kind: 'parent' },
    { name: 'description', kind: 'textarea', max: 2000 },
  ],
  desks: [{ name: 'code', kind: 'text', max: 50, required: true, createOnly: true }],
};

const KINDS: { kind: StructureKind; view: string; manage: string; feature?: 'esm' }[] = [
  { kind: 'sites', view: 'sites.view', manage: 'sites.manage' },
  { kind: 'departments', view: 'departments.view', manage: 'departments.manage' },
  { kind: 'groups', view: 'groups.view', manage: 'groups.manage' },
  // Desks are for enterprise service management (ESM): shown only with the feature (D-061).
  { kind: 'desks', view: 'groups.view', manage: 'settings.manage', feature: 'esm' },
];

/** Admin › Organisation (WP-021): sites, departments, support groups and desks. */
export function OrganizationPage() {
  const t = useLabel();
  const { can } = useAccess();
  const licence = useLicence();
  const navigate = useNavigate();
  const { section } = useParams();
  const tabs = KINDS.filter(
    (k) => can(k.view) && (k.feature === undefined || licence.has(k.feature)),
  );
  const first = tabs[0];
  if (first === undefined) return <NoAccess titleKey="nav.admin_organization" />;
  const active = tabs.find((k) => k.kind === section);
  if (active === undefined) return <Navigate to={`/admin/organization/${first.kind}`} replace />;
  return (
    <Tabs
      activeKey={active.kind}
      onChange={(key) => void navigate(`/admin/organization/${key}`)}
      items={tabs.map((k) => ({
        key: k.kind,
        label: t(`organization.${k.kind}`),
        children: <UnitsTab kind={k.kind} editable={can(k.manage)} />,
      }))}
    />
  );
}

/** A text field an admin typed (shown as written). */
function typedText(row: Row, name: string): string {
  const value = row[name];
  return typeof value === 'string' ? value : '';
}

function unitName(row: Row, t: ReturnType<typeof useLabel>, language: string): string {
  if (typeof row.name === 'string') return row.name;
  const labels = row.labels as Record<string, string> | undefined;
  return labels?.[language] ?? labels?.en ?? t(`desk.${String(row.code)}`);
}

function UnitsTab({ kind, editable }: { kind: StructureKind; editable: boolean }) {
  const t = useLabel();
  const listFormat = useListFormat();
  const { message } = App.useApp();
  const rows = useStructure(kind);
  const { remove } = useStructureChange(kind);
  const [editing, setEditing] = useState<Row | 'new'>();
  // Live: a change by another admin arrives as organization.structure_changed on the tenant's
  // channel; ConsoleLayout refreshes these lists.
  const sites = useStructure('sites', kind === 'groups' || kind === 'departments');
  const siteName = useMemo(
    () => new Map((sites.data ?? []).map((s) => [s.id, s.name])),
    [sites.data],
  );
  const data = (rows.data ?? []) as unknown as Row[];
  const language = document.documentElement.lang || 'en';

  // A unit someone changed before it was removed (409): the shared dialog (QA WP-029 BUG-05).
  const conflict = useConflict();
  const [removing, setRemoving] = useState<Row>();
  const live = data.find((r) => r.id === removing?.id);
  const removeRow = (row: Row, version = row.version) => {
    remove.mutate(
      { id: row.id, version },
      {
        onSuccess: () => {
          void message.success(t('organization.removed', { name: unitName(row, t, language) }));
        },
        onError: (error) => {
          if (error instanceof ApiError && error.code.endsWith('_in_use')) {
            // Say what still uses it, so the admin knows to make it inactive instead.
            const uses = listFormat(
              Object.entries(error.params).map(([what, count]) =>
                t(`organization.uses.${what}`, { count: Number(count) }),
              ),
              'conjunction',
            );
            markHandled(error); // said here, with what still uses it
            void message.warning(t('organization.in_use', { uses }));
            return;
          }
          if (conflict.take(error)) {
            setRemoving(row);
            return;
          }
          reportError(error);
        },
      },
    );
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Flex justify="space-between" align="baseline" wrap gap={8}>
        <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
          {t(`organization.${kind}.explain`)}
        </Typography.Paragraph>
        {editable && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing('new');
            }}
            data-testid={`${kind}-add`}
          >
            {t(`organization.${kind}.add`)}
          </Button>
        )}
      </Flex>
      <Table<Row>
        rowKey="id"
        loading={rows.isPending}
        dataSource={data}
        pagination={false}
        data-testid={`${kind}-table`}
        onRow={(row) => ({
          onClick: () => {
            if (editable) setEditing(row);
          },
          style: editable ? { cursor: 'pointer' } : undefined,
          'data-testid': `${kind}-row-${unitName(row, t, language)}`,
        })}
        columns={[
          {
            key: 'name',
            title: t('organization.col.name'),
            render: (_, row) => (
              <Flex gap={6} wrap align="center">
                <bdi>{unitName(row, t, language)}</bdi>
                {row.is_default === true && (
                  <ToneTag tone="info">{t('organization.default')}</ToneTag>
                )}
                {row.disabled && <ToneTag tone="warning">{t('organization.inactive')}</ToneTag>}
              </Flex>
            ),
          },
          ...(kind === 'departments'
            ? [
                {
                  key: 'code',
                  title: t('organization.field.code'),
                  // A department code is the admin's own text (like a name), not a system code.
                  render: (_: unknown, row: Row) => <bdi>{typedText(row, 'code')}</bdi>,
                },
              ]
            : []),
          ...(kind === 'groups' || kind === 'departments'
            ? [
                {
                  key: 'sites',
                  // One site per department, several per group (QA WP-021 C1).
                  title: t(
                    kind === 'departments'
                      ? 'organization.field.site_id'
                      : 'organization.field.site_ids',
                  ),
                  render: (_: unknown, row: Row) => {
                    const ids =
                      (row.site_ids as string[] | undefined) ??
                      (row.site_id ? [row.site_id as string] : []);
                    return listFormat(ids.map((id) => siteName.get(id) ?? ''));
                  },
                },
              ]
            : []),
          ...(kind === 'sites' || kind === 'groups'
            ? [
                {
                  key: 'members',
                  title: t('organization.col.members'),
                  render: (_: unknown, row: Row) => (row.member_ids as string[]).length,
                },
              ]
            : []),
          ...(editable && kind !== 'desks'
            ? [
                {
                  key: 'actions',
                  title: <span className="sr-only">{t('organization.col.actions')}</span>,
                  render: (_: unknown, row: Row) =>
                    row.is_default === true ? null : (
                      <Popconfirm
                        title={t('organization.remove.confirm', {
                          name: unitName(row, t, language),
                        })}
                        okText={t('organization.remove')}
                        cancelText={t('actions.cancel')}
                        onConfirm={() => {
                          removeRow(row);
                        }}
                        onPopupClick={(event) => {
                          event.stopPropagation();
                        }}
                      >
                        <Button
                          danger
                          size="small"
                          onClick={(event) => {
                            event.stopPropagation();
                          }}
                          data-testid={`${kind}-remove-${unitName(row, t, language)}`}
                        >
                          {t('organization.remove')}
                        </Button>
                      </Popconfirm>
                    ),
                },
              ]
            : []),
        ]}
      />
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={(field) => t(`organization.field.${field}`)}
        opened={unitView(kind, removing)}
        latest={unitView(kind, live)}
        onReload={() => {
          conflict.clear();
          setRemoving(undefined);
        }}
        onKeepMine={() => {
          conflict.clear();
          if (live !== undefined) removeRow(live, conflict.latestVersion ?? live.version);
          setRemoving(undefined);
        }}
      />
      <UnitEditor
        kind={kind}
        row={editing === 'new' ? undefined : editing}
        open={editing !== undefined}
        latest={
          editing === 'new' || editing === undefined
            ? undefined
            : data.find((r) => r.id === editing.id)
        }
        onClose={() => {
          setEditing(undefined);
        }}
      />
    </Space>
  );
}

function initial(kind: StructureKind, row: Row | undefined): Record<string, unknown> {
  if (row === undefined) return kind === 'groups' ? { site_ids: [] } : {};
  const values: Record<string, unknown> = { disabled: row.disabled };
  for (const field of FIELDS[kind]) values[field.name] = row[field.name] ?? null;
  if (kind === 'desks') {
    const labels = (row.labels as Record<string, string> | undefined) ?? {};
    values.label_en = labels.en ?? '';
    values.label_ar = labels.ar ?? '';
    values.label_ur = labels.ur ?? '';
  }
  return values;
}

/** What a person edits of a unit, by the form's field names, for the conflict dialog. */
function unitView(kind: StructureKind, row: Row | undefined): object | undefined {
  if (row === undefined) return undefined;
  const names = [...FIELDS[kind].map((field) => field.name), 'disabled'];
  if (kind === 'desks') names.push('labels');
  return Object.fromEntries(names.map((name) => [name, row[name] ?? null]));
}

/** Add or change one unit. Keeps the version it opened; a save elsewhere shows the conflict. */
function UnitEditor({
  kind,
  row,
  latest,
  open,
  onClose,
}: {
  kind: StructureKind;
  row: Row | undefined;
  latest: Row | undefined;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { can } = useAccess();
  const me = useSession().data?.user.id;
  const { message } = App.useApp();
  const { create, update } = useStructureChange(kind);
  const [form] = Form.useForm<Record<string, unknown>>();
  const [problems, setProblems] = useState<Record<string, string>>({});
  // A refusal with no field to point at (a rule, a limit) is shown above Save (QA WP-029 BUG-02).
  const problem = useFormProblem();
  const [conflict, setConflict] = useState<unknown>();
  const [version, setVersion] = useState<number | undefined>(row?.version);
  const [opened, setOpened] = useState<string | undefined>(row?.id);
  // The unit as this form is based on it: the conflict dialog compares it with the live one
  // (units keep no field history, so the server cannot name the fields: QA WP-029 BUG-05).
  const [base, setBase] = useState<Row | undefined>(row);
  if (row?.id !== opened) {
    setOpened(row?.id);
    setVersion(row?.version);
    setBase(row);
    setProblems({});
    problem.clear();
  }
  const stale = latest !== undefined && version !== undefined && latest.version !== version;

  const body = (values: Record<string, unknown>) => {
    const out: Record<string, unknown> = {};
    for (const field of FIELDS[kind]) {
      if (row !== undefined && field.createOnly) continue;
      const value = values[field.name];
      out[field.name] = typeof value === 'string' && value.trim() === '' ? null : (value ?? null);
    }
    if (kind === 'desks') {
      const labels: Record<string, string> = {};
      for (const language of ['en', 'ar', 'ur']) {
        const label = values[`label_${language}`];
        if (typeof label === 'string' && label.trim() !== '') labels[language] = label.trim();
      }
      out.labels = labels;
    }
    if (row !== undefined) out.disabled = values.disabled === true;
    return out;
  };

  const failed = (error: unknown) => {
    if (error instanceof ApiError && error.isConflict && error.code === 'version_conflict') {
      setConflict(error);
      return;
    }
    if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
      markHandled(error);
      setProblems(
        Object.fromEntries(
          error.fieldErrors.map((f) => [
            f.field.replace(/^body\./, '').replace(/^labels.*/, 'label_en'),
            t(f.message_key, f.params ?? {}),
          ]),
        ),
      );
      return;
    }
    problem.show(error);
  };

  const save = (values: Record<string, unknown>, at = version) => {
    setProblems({});
    problem.clear();
    const done = () => {
      void message.success(t('common.saved'));
      onClose();
    };
    if (row === undefined) {
      create.mutate(body(values) as never, { onSuccess: done, onError: failed });
    } else {
      update.mutate(
        { id: row.id, version: at ?? row.version, body: body(values) },
        { onSuccess: done, onError: failed },
      );
    }
  };

  const help = (name: string) =>
    problems[name] === undefined ? {} : { validateStatus: 'error' as const, help: problems[name] };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={520}
      destroyOnHidden
      title={row === undefined ? t(`organization.${kind}.add`) : t(`organization.${kind}.edit`)}
      data-testid={`${kind}-editor`}
    >
      {stale && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('organization.changed_elsewhere')}
          data-testid="unit-stale"
        />
      )}
      <Form
        form={form}
        layout="vertical"
        initialValues={initial(kind, row)}
        onFinish={(values) => {
          save(values);
        }}
      >
        {FIELDS[kind]
          .filter((field) => row === undefined || !field.createOnly)
          .map((field) => (
            <Form.Item
              key={field.name}
              name={field.name}
              label={t(`organization.field.${field.name}`)}
              required={field.required}
              {...help(field.name)}
            >
              <FieldInput field={field} unitId={row?.id} />
            </Form.Item>
          ))}
        {kind === 'desks' &&
          (['en', 'ar', 'ur'] as const).map((language) => (
            <Form.Item
              key={language}
              name={`label_${language}`}
              label={t('organization.field.label', { language: t(`locale.${language}`) })}
              required={language === 'en'}
              {...help(`label_${language}`)}
            >
              <Input count={lengthLimit(100)} dir={language === 'en' ? 'ltr' : 'rtl'} />
            </Form.Item>
          ))}
        {row !== undefined && row.is_default !== true && (
          <Form.Item
            name="disabled"
            label={t('organization.field.disabled')}
            valuePropName="checked"
            extra={t('organization.field.disabled.help')}
          >
            <Switch data-testid="unit-disabled" />
          </Form.Item>
        )}
        <FormProblem problem={problem} />
        <Button
          type="primary"
          htmlType="submit"
          loading={create.isPending || update.isPending}
          data-testid="unit-save"
        >
          {t('actions.save')}
        </Button>
      </Form>
      {kind === 'groups' && row !== undefined && (
        <>
          <Divider />
          <Typography.Title level={2} style={{ fontSize: 16 }}>
            {t('availability.group_members')}
          </Typography.Title>
          {/* The lead or an admin sets a sick member Away (QA WP-029 follow-up). */}
          <GroupMembersAvailability
            groupId={row.id}
            canSet={can('users.manage') || (me !== undefined && row.lead_id === me)}
          />
        </>
      )}
      <ConflictDialog
        open={conflict !== undefined}
        error={conflict}
        fieldLabel={(field) => t(`organization.field.${field}`)}
        opened={unitView(kind, base)}
        latest={unitView(kind, latest)}
        onReload={() => {
          setConflict(undefined);
          onClose();
        }}
        onKeepMine={() => {
          setConflict(undefined);
          if (latest === undefined) return;
          setBase(latest);
          setVersion(latest.version);
          save(form.getFieldsValue(), latest.version);
        }}
      />
    </Drawer>
  );
}

const ZONES: string[] =
  typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : [];

function FieldInput({
  field,
  unitId,
  value,
  onChange,
}: {
  field: FieldSpec;
  unitId: string | undefined;
  value?: unknown;
  onChange?: (value: unknown) => void;
}): ReactNode {
  const t = useLabel();
  const sites = useStructure('sites', ['site', 'sites'].includes(field.kind));
  const departments = useStructure('departments', field.kind === 'parent');
  const desks = useStructure('desks', field.kind === 'desk');
  const [search, setSearch] = useState('');
  const people = useUsers({ q: search, limit: 20 }, field.kind === 'person');
  const common = { value: value ?? undefined, onChange, 'data-testid': `unit-${field.name}` };
  switch (field.kind) {
    case 'text':
      return (
        <Input
          {...common}
          value={(value as string | null) ?? ''}
          onChange={(event) => onChange?.(event.target.value)}
          count={lengthLimit(field.max ?? 200)}
        />
      );
    case 'textarea':
      return (
        <Input.TextArea
          {...common}
          rows={3}
          value={(value as string | null) ?? ''}
          onChange={(event) => onChange?.(event.target.value)}
          count={lengthLimit(field.max ?? 2000)}
        />
      );
    case 'language':
      return (
        <Select
          {...common}
          allowClear
          options={['en', 'ar', 'ur'].map((code) => ({ value: code, label: t(`locale.${code}`) }))}
        />
      );
    case 'timezone':
      return (
        <Select
          {...common}
          allowClear
          showSearch
          options={ZONES.map((zone) => ({ value: zone, label: zone }))}
        />
      );
    case 'site':
    case 'sites':
      return (
        <Select
          {...common}
          allowClear
          showSearch
          optionFilterProp="label"
          mode={field.kind === 'sites' ? 'multiple' : undefined}
          options={(sites.data ?? [])
            .filter(
              (s) => !s.disabled || (Array.isArray(value) ? value.includes(s.id) : value === s.id),
            )
            .map((s) => ({ value: s.id, label: s.name }))}
        />
      );
    case 'parent':
      return (
        <Select
          {...common}
          allowClear
          showSearch
          optionFilterProp="label"
          options={(departments.data ?? [])
            .filter((d) => d.id !== unitId)
            .map((d) => ({ value: d.id, label: d.name }))}
        />
      );
    case 'desk':
      return (
        <Select
          {...common}
          options={(desks.data ?? []).map((d) => ({
            value: d.id,
            label: d.labels.en ?? t(`desk.${d.code}`),
          }))}
        />
      );
    case 'person': {
      const found = people.data?.pages.flatMap((page) => page.items) ?? [];
      const options = found.map((p) => ({ value: p.id, label: p.display_name }));
      if (typeof value === 'string' && !options.some((o) => o.value === value)) {
        options.unshift({ value, label: t('organization.current_person') });
      }
      return (
        <Select
          {...common}
          allowClear
          showSearch
          filterOption={false}
          onSearch={setSearch}
          options={options}
        />
      );
    }
  }
}
