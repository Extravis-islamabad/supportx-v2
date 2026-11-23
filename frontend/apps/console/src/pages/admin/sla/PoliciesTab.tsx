import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import {
  Alert,
  App,
  Button,
  Checkbox,
  Flex,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';

import {
  ApiError,
  useIncidentListFields,
  useSlaCalendars,
  useSlaPolicies,
  useSlaPolicyChange,
  useSlaSettings,
  useSlaSettingsChange,
  type SlaLevel,
  type SlaPolicy,
  type SlaSettings,
  type SlaTargetRow,
} from '@supportx/api-client';
import { FilterBuilder, fromDsl, rowProblems, toDsl, type FilterModel } from '@supportx/forms';
import {
  ConflictDialog,
  Drawer,
  FormProblem,
  lengthLimit,
  markHandled,
  reportError,
  SettingsCard,
  StickySaveBar,
  ToneTag,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

import { builderFields } from '../../incidents/list/model';
import { useReportWords } from '../../reports/names';
import { LevelsEditor } from './LevelsEditor';
import { calendarNameOf, policyName } from './names';

type Translate = ReturnType<typeof useLabel>;
type Kind = SlaTargetRow['kind'];
type Unit = SlaTargetRow['unit'];
type Source = SlaTargetRow['source'];

const RECORD_TYPE = 'incident'; // the settings tab's type (its own choice comes later)
// Every type with SLAs (WP-045d S3, the coordinator): their policies are made here.
const POLICY_TYPES = ['incident', 'service_request', 'problem', 'change'] as const;
type PolicyType = (typeof POLICY_TYPES)[number];
const KINDS: Kind[] = ['first_response', 'resolution'];
const UNITS: Unit[] = ['minutes', 'hours', 'business_days'];
const SOURCES: Source[] = ['site', 'group', 'fixed', 'around_the_clock'];
// null: a row for every priority; the incident priorities after it, highest first.
const PRIORITIES: (string | null)[] = [null, 'p1', 'p2', 'p3', 'p4'];
// SLA fields and timestamps are not conditions (the API refuses them; see work_items/service/sla.py).
const NOT_CONDITIONS = new Set([
  'sla_policy_id',
  'resolution_due_at',
  'first_response_due_at',
  'first_responded_at',
  'first_response_sla_state',
  'resolution_sla_state',
  'first_response_breached',
  'resolution_breached',
  'paused_seconds',
  'created_at',
  'updated_at',
  'status_changed_at',
  'first_assigned_at',
  'resolved_at',
  'closed_at',
]);

function priorityName(t: Translate, priority: string | null | undefined): string {
  return priority === null || priority === undefined
    ? t('sla.policies.every_priority')
    : t(`priority.${priority}`);
}

function amountText(t: Translate, row: SlaTargetRow): string {
  return `${String(row.amount ?? '')} ${t(`sla_target_unit.${row.unit}`)}`;
}

/** Admin › SLA › Policies (WP-025 session 2): first match wins; the default policy is last. */
export function PoliciesTab({ editable }: { editable: boolean }) {
  const t = useLabel();
  const { message } = App.useApp();
  const [recordType, setRecordType] = useState<PolicyType>('incident');
  // Live: changes arrive as `sla.setup.changed` on the tenant channel (ConsoleLayout).
  const policies = useSlaPolicies(recordType);
  const { remove, reorder } = useSlaPolicyChange(recordType);
  const [editing, setEditing] = useState<SlaPolicy | 'new'>();
  const rows = policies.data ?? [];
  const movable = rows.filter((p) => !p.fallback);
  const live = editing === 'new' ? undefined : rows.find((r) => r.id === editing?.id);

  const move = (policy: SlaPolicy, step: -1 | 1) => {
    const ids = movable.map((p) => p.id);
    const from = ids.indexOf(policy.id);
    const to = from + step;
    if (from < 0 || to < 0 || to >= ids.length) return;
    [ids[from], ids[to]] = [ids[to] ?? '', ids[from] ?? ''];
    reorder.mutate(ids, {
      onSuccess: () => void message.success(t('common.saved')),
      onError: reportError,
    });
  };

  // No target anywhere (a new tenant's changes: Appendix A sets none): say so in plain words.
  const untargeted =
    policies.data !== undefined &&
    rows.every((p) => p.targets.every((r) => r.amount === null || r.amount === undefined));
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Select<PolicyType>
        style={{ minWidth: 220, alignSelf: 'flex-start' }}
        prefix={`${t('sla.policies.record_type')}:`}
        aria-label={t('sla.policies.record_type')}
        value={recordType}
        onChange={(value) => {
          setRecordType(value);
          setEditing(undefined);
        }}
        options={POLICY_TYPES.map((code) => ({
          value: code,
          label: t(`work_item_type.${code}`),
        }))}
        data-testid="sla-policy-type"
      />
      <Flex justify="space-between" align="baseline" wrap gap={8}>
        <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
          {t('sla.policies.explain')}
        </Typography.Paragraph>
        {editable && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing('new');
            }}
            data-testid="sla-policy-add"
          >
            {t('sla.policies.add')}
          </Button>
        )}
      </Flex>
      {untargeted && (
        <Alert
          type="info"
          showIcon
          message={t('sla.policies.no_targets', { type: t(`work_item_type.${recordType}`) })}
          data-testid="sla-policies-no-targets"
        />
      )}
      <Table<SlaPolicy>
        rowKey="id"
        loading={policies.isPending}
        dataSource={rows}
        pagination={false}
        data-testid="sla-policies"
        scroll={{ x: 'max-content' }}
        onRow={(row) => ({
          onClick: () => {
            if (editable && row.can_manage) setEditing(row);
          },
          style: editable ? { cursor: 'pointer' } : undefined,
          'data-testid': `sla-policy-row-${row.id}`,
        })}
        columns={[
          {
            key: 'name',
            title: t('sla.policy.field.name'),
            render: (_, row) => (
              <Flex gap={6} wrap align="center">
                <bdi>{policyName(t, row.name)}</bdi>
                {row.fallback && <ToneTag tone="info">{t('sla.policies.default')}</ToneTag>}
                {!row.enabled && <ToneTag tone="default">{t('sla.policies.off')}</ToneTag>}
                {row.never_matches && (
                  <span data-testid={`sla-policy-never-${row.id}`}>
                    <ToneTag tone="warning">{t('sla.policies.never_matches')}</ToneTag>
                  </span>
                )}
              </Flex>
            ),
          },
          {
            key: 'applies',
            title: t('sla.policy.field.conditions'),
            render: (_, row) =>
              row.conditions === null
                ? t('sla.policies.all_records')
                : t('sla.policies.with_conditions'),
          },
          ...KINDS.map((kind) => ({
            key: kind,
            title: t(`sla_target_kind.${kind}`),
            render: (_: unknown, row: SlaPolicy) => (
              <Space direction="vertical" size={0}>
                {row.targets
                  .filter((r) => r.kind === kind && r.amount !== null && r.amount !== undefined)
                  .map((r) => (
                    <Typography.Text key={r.priority ?? 'all'}>
                      {priorityName(t, r.priority)}: {amountText(t, r)}
                    </Typography.Text>
                  ))}
              </Space>
            ),
          })),
          ...(editable
            ? [
                {
                  key: 'actions',
                  title: '',
                  render: (_: unknown, row: SlaPolicy) =>
                    row.fallback || !row.can_manage ? null : (
                      <Space size={0}>
                        {/* Keyboard reordering: buttons, not only dragging (wp-025-plan §3.7). */}
                        <Button
                          type="text"
                          icon={<ArrowUpOutlined />}
                          aria-label={t('sla.policies.move_up')}
                          disabled={movable[0]?.id === row.id || reorder.isPending}
                          onClick={(event) => {
                            event.stopPropagation();
                            move(row, -1);
                          }}
                          data-testid={`sla-policy-up-${row.id}`}
                        />
                        <Button
                          type="text"
                          icon={<ArrowDownOutlined />}
                          aria-label={t('sla.policies.move_down')}
                          disabled={movable.at(-1)?.id === row.id || reorder.isPending}
                          onClick={(event) => {
                            event.stopPropagation();
                            move(row, 1);
                          }}
                          data-testid={`sla-policy-down-${row.id}`}
                        />
                        <Popconfirm
                          title={t('sla.policies.delete_confirm')}
                          onConfirm={(event) => {
                            event?.stopPropagation();
                            remove.mutate(
                              { id: row.id, version: row.version },
                              {
                                onSuccess: () => void message.success(t('common.saved')),
                                onError: reportError,
                              },
                            );
                          }}
                        >
                          <Button
                            type="text"
                            icon={<DeleteOutlined />}
                            aria-label={t('sla.policies.delete')}
                            onClick={(event) => {
                              event.stopPropagation();
                            }}
                            data-testid={`sla-policy-delete-${row.id}`}
                          />
                        </Popconfirm>
                      </Space>
                    ),
                },
              ]
            : []),
        ]}
      />
      {editing !== undefined && (
        <PolicyEditor
          recordType={recordType}
          row={editing === 'new' ? undefined : editing}
          latest={live}
          onClose={() => {
            setEditing(undefined);
          }}
        />
      )}
    </Space>
  );
}

interface PolicyValues {
  name: string;
  description?: string;
  enabled: boolean;
  pausing: Kind[];
}

function fieldProblems(error: ApiError, t: Translate): Record<string, string> {
  return Object.fromEntries(
    error.fieldErrors.map((f) => [
      f.field.replace(/^body\./, '').replace(/\..*$/, ''),
      t(f.message_key, f.params ?? {}),
    ]),
  );
}

function PolicyEditor({
  recordType,
  row,
  latest,
  onClose,
}: {
  recordType: PolicyType;
  row: SlaPolicy | undefined;
  latest: SlaPolicy | undefined;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const { create, update } = useSlaPolicyChange(recordType);
  const calendars = useSlaCalendars();
  const listFields = useIncidentListFields(true);
  const words = useReportWords();
  const [form] = Form.useForm<PolicyValues>();
  const problem = useFormProblem();
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [targets, setTargets] = useState<SlaTargetRow[]>(row?.targets ?? []);
  // The stored levels, as the API takes them back (their position is their order per kind).
  const [levels, setLevels] = useState<SlaLevel[]>(
    (row?.levels ?? []).map((level) => ({
      kind: level.kind,
      anchor: level.anchor,
      offset_seconds: level.offset_seconds,
      recipients: level.recipients,
      fallback: level.fallback,
      actions: level.actions,
      notify: level.notify,
    })),
  );
  const parsed = useMemo(() => fromDsl(row?.conditions ?? null), [row?.conditions]);
  const [filter, setFilter] = useState<FilterModel>(parsed ?? { join: 'and', rows: [] });
  const [conflict, setConflict] = useState<unknown>();
  // One Idempotency-Key per form: a retried save never makes a second policy.
  const [key] = useState(() => crypto.randomUUID());
  const fallback = row?.fallback === true;
  const stale = latest !== undefined && row !== undefined && latest.version !== row.version;
  const fields = useMemo(
    () =>
      builderFields(
        (listFields.data ?? []).filter((f) => !NOT_CONDITIONS.has(f.name)),
        words,
      ),
    [listFields.data, words],
  );
  const filterBad = rowProblems(filter).size > 0;

  const failed = (error: unknown) => {
    if (error instanceof ApiError && error.isConflict && error.code === 'version_conflict') {
      setConflict(error);
      return;
    }
    if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
      markHandled(error);
      setProblems(fieldProblems(error, t));
      return;
    }
    problem.show(error);
  };

  const save = (values: PolicyValues, version = row?.version) => {
    setProblems({});
    problem.clear();
    const done = () => {
      void message.success(t('common.saved'));
      onClose();
    };
    const body = {
      name: values.name,
      description: values.description?.trim() ? values.description.trim() : null,
      enabled: values.enabled,
      pausing: values.pausing,
      targets: targets.filter((r) => r.amount !== null && r.amount !== undefined),
      levels,
      // The default policy applies to everything: it has no conditions (D-074).
      ...(fallback || parsed === null ? {} : { conditions: toDsl(filter) ?? null }),
    };
    if (row === undefined) {
      create.mutate({ body, key }, { onSuccess: done, onError: failed });
      return;
    }
    update.mutate(
      { id: row.id, version: version ?? row.version, body },
      { onSuccess: done, onError: failed },
    );
  };

  const cell = (kind: Kind, priority: string | null) =>
    targets.find((r) => r.kind === kind && (r.priority ?? null) === priority);
  const setCell = (kind: Kind, priority: string | null, change: Partial<SlaTargetRow>) => {
    setTargets((current) => {
      const others = current.filter((r) => !(r.kind === kind && (r.priority ?? null) === priority));
      const found = current.find((r) => r.kind === kind && (r.priority ?? null) === priority);
      const next: SlaTargetRow = {
        kind,
        priority,
        amount: null,
        unit: 'hours',
        source: 'site',
        fixed_calendar_id: null,
        ...found,
        ...change,
      };
      if (next.source !== 'fixed') next.fixed_calendar_id = null;
      return [...others, next];
    });
  };
  const help = (name: string) =>
    problems[name] === undefined ? {} : { validateStatus: 'error' as const, help: problems[name] };

  return (
    <>
      <Drawer
        open
        onClose={onClose}
        width={760}
        destroyOnHidden
        title={row === undefined ? t('sla.policies.add') : t('sla.policies.edit')}
        data-testid="sla-policy-editor"
        extra={
          <Button
            type="primary"
            loading={create.isPending || update.isPending}
            disabled={filterBad}
            onClick={() => {
              form.submit();
            }}
            data-testid="sla-policy-save"
          >
            {t('actions.save')}
          </Button>
        }
      >
        {stale && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message={t('organization.changed_elsewhere')}
          />
        )}
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('sla.policies.running_records_keep')}
        />
        <FormProblem problem={problem} />
        <Form<PolicyValues>
          form={form}
          layout="vertical"
          initialValues={{
            name: row?.name ?? '',
            description: row?.description ?? '',
            enabled: row?.enabled ?? true,
            pausing: row?.pausing ?? KINDS,
          }}
          onFinish={(values) => {
            save(values);
          }}
        >
          <Form.Item
            name="name"
            label={t('sla.policy.field.name')}
            rules={[{ required: true, message: t('errors.field.required') }]}
            {...help('name')}
          >
            <Input count={lengthLimit(200)} data-testid="sla-policy-name" />
          </Form.Item>
          <Form.Item name="description" label={t('sla.policy.field.description')}>
            <Input.TextArea count={lengthLimit(2000)} autoSize={{ minRows: 2 }} />
          </Form.Item>
          {!fallback && (
            <Form.Item name="enabled" label={t('sla.policy.field.enabled')} valuePropName="checked">
              <Switch data-testid="sla-policy-enabled" />
            </Form.Item>
          )}
          <Form.Item name="pausing" label={t('sla.policy.field.pausing')} {...help('pausing')}>
            <Checkbox.Group
              options={KINDS.map((kind) => ({ value: kind, label: t(`sla_target_kind.${kind}`) }))}
            />
          </Form.Item>
          {!fallback && (
            <Form.Item label={t('sla.policy.field.conditions')} {...help('conditions')}>
              {parsed === null ? (
                <Alert type="info" showIcon message={t('sla.policies.conditions_complex')} />
              ) : (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Typography.Text type="secondary">
                    {t('sla.policies.conditions_explain')}
                  </Typography.Text>
                  <FilterBuilder
                    fields={fields}
                    value={filter}
                    onChange={setFilter}
                    testId="sla-policy-conditions"
                  />
                </Space>
              )}
            </Form.Item>
          )}
          <Form.Item label={t('sla.policy.field.targets')} {...help('targets')}>
            <Typography.Paragraph type="secondary">
              {t('sla.policies.targets_explain')}
            </Typography.Paragraph>
            <Table<string | null>
              rowKey={(p) => p ?? 'all'}
              dataSource={PRIORITIES}
              pagination={false}
              size="small"
              scroll={{ x: 'max-content' }}
              data-testid="sla-policy-targets"
              columns={[
                {
                  key: 'priority',
                  title: t('work_item.field.priority'),
                  render: (_, priority) => priorityName(t, priority),
                },
                ...KINDS.map((kind) => ({
                  key: kind,
                  title: t(`sla_target_kind.${kind}`),
                  render: (_: unknown, priority: string | null) => {
                    const found = cell(kind, priority);
                    const id = `${kind}-${priority ?? 'all'}`;
                    return (
                      <Space direction="vertical" size={4}>
                        <Space.Compact>
                          <InputNumber
                            min={1}
                            max={100000}
                            value={found?.amount ?? null}
                            onChange={(amount) => {
                              setCell(kind, priority, { amount });
                            }}
                            aria-label={`${t(`sla_target_kind.${kind}`)} · ${priorityName(t, priority)}`}
                            data-testid={`sla-target-amount-${id}`}
                          />
                          <Select<Unit>
                            value={found?.unit ?? 'hours'}
                            onChange={(unit) => {
                              setCell(kind, priority, { unit });
                            }}
                            options={UNITS.map((u) => ({
                              value: u,
                              label: t(`sla_target_unit.${u}`),
                            }))}
                            style={{ minWidth: 130 }}
                            aria-label={t('sla.policy.field.unit')}
                          />
                        </Space.Compact>
                        {found?.amount !== null && found?.amount !== undefined && (
                          <Select<Source>
                            value={found.source}
                            onChange={(source) => {
                              setCell(kind, priority, { source });
                            }}
                            options={SOURCES.map((s) => ({
                              value: s,
                              label: t(`sla_calendar_source.${s}`),
                            }))}
                            style={{ minWidth: 200 }}
                            aria-label={t('sla.policy.field.calendar')}
                          />
                        )}
                        {found?.source === 'fixed' && (
                          <Select<string>
                            value={found.fixed_calendar_id ?? undefined}
                            onChange={(calendar) => {
                              setCell(kind, priority, { fixed_calendar_id: calendar });
                            }}
                            options={(calendars.data ?? []).map((c) => ({
                              value: c.id,
                              label: calendarNameOf(t, c.name),
                            }))}
                            placeholder={t('sla.policy.field.calendar')}
                            style={{ minWidth: 200 }}
                            aria-label={t('sla.policy.field.calendar')}
                          />
                        )}
                      </Space>
                    );
                  },
                })),
              ]}
            />
          </Form.Item>
          <Form.Item label={t('sla.policy.field.levels')} {...help('levels')}>
            <LevelsEditor levels={levels} onChange={setLevels} />
          </Form.Item>
        </Form>
      </Drawer>
      <ConflictDialog
        open={conflict !== undefined}
        error={conflict}
        fieldLabel={(name) => t(`sla.policy.field.${name}`)}
        onReload={() => {
          setConflict(undefined);
          onClose();
        }}
        onKeepMine={() => {
          setConflict(undefined);
          save(form.getFieldsValue(), latest?.version);
        }}
      />
    </>
  );
}

// --- settings ------------------------------------------------------------------------------------

/** Admin › SLA › Settings: the warning point and what priority changes and reopens do. */
const SETTING_FIELDS = ['warning_percent', 'priority_rule', 'reopen_rule'] as const;
type SlaSettingsValues = Pick<SlaSettings, (typeof SETTING_FIELDS)[number]>;

/** The SLA settings (template E, D-147): one card, one save bar sending only what changed. */
export function SettingsTab({ editable }: { editable: boolean }) {
  const t = useLabel();
  const { message } = App.useApp();
  const settings = useSlaSettings(RECORD_TYPE);
  const change = useSlaSettingsChange(RECORD_TYPE);
  const problem = useFormProblem();
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [form] = Form.useForm<SlaSettingsValues>();
  const watched = Form.useWatch([], form) as Partial<SlaSettingsValues> | undefined;
  const current = settings.data;
  if (current === undefined) return null;
  const changed = SETTING_FIELDS.filter(
    (name) => watched?.[name] !== undefined && watched[name] !== current[name],
  );
  return (
    <Form
      form={form}
      layout="vertical"
      disabled={!editable}
      key={current.version} // a save made elsewhere arrives live: show it
      initialValues={current}
      data-testid="sla-settings"
      onFinish={(values) => {
        setProblems({});
        problem.clear();
        const body = Object.fromEntries(
          changed.map((name) => [name, values[name]]),
        ) as Partial<SlaSettingsValues>;
        change.mutate(
          { version: current.version, body },
          {
            onSuccess: () => void message.success(t('common.saved')),
            onError: (error) => {
              if (error instanceof ApiError && error.status === 422) {
                markHandled(error);
                setProblems(fieldProblems(error, t));
                return;
              }
              problem.show(error);
            },
          },
        );
      }}
    >
      <FormProblem problem={problem} />
      <SettingsCard title={t('sla.settings.title')} testId="sla-settings-card">
        <div style={{ maxWidth: 560 }}>
          <Form.Item
            name="warning_percent"
            label={t('sla.settings.warning_percent')}
            extra={t('sla.settings.warning_percent_help')}
            {...(problems.warning_percent === undefined
              ? {}
              : { validateStatus: 'error' as const, help: problems.warning_percent })}
          >
            <InputNumber min={1} max={99} suffix="%" data-testid="sla-settings-warning" />
          </Form.Item>
          <Form.Item name="priority_rule" label={t('sla.settings.priority_rule')}>
            <Select
              options={(['recalculate', 'restart'] as const).map((v) => ({
                value: v,
                label: t(`sla_priority_rule.${v}`),
              }))}
            />
          </Form.Item>
          <Form.Item name="reopen_rule" label={t('sla.settings.reopen_rule')}>
            <Select
              options={(['resume', 'restart'] as const).map((v) => ({
                value: v,
                label: t(`sla_reopen_rule.${v}`),
              }))}
            />
          </Form.Item>
        </div>
      </SettingsCard>
      {editable && (
        <StickySaveBar
          changes={changed.length}
          saving={change.isPending}
          onDiscard={() => {
            form.resetFields();
            setProblems({});
          }}
          onSave={() => {
            form.submit();
          }}
          testId="sla-settings-save-bar"
        />
      )}
    </Form>
  );
}
