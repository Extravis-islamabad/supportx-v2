import { ArrowDownOutlined, ArrowUpOutlined, PlusOutlined } from '@ant-design/icons';
import {
  Alert,
  App,
  Button,
  Card,
  Drawer,
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
  useAutomationChange,
  useGroupAssignment,
  useRoutingRules,
  useRoutingSettings,
  useRuleFields,
  useSaveGroupAssignment,
  useStructure,
  type AssignmentSettingsOut,
  type RoutingOut,
} from '@supportx/api-client';
import {
  FormProblem,
  ConflictDialog,
  ToneTag,
  lengthLimit,
  markHandled,
  reportError,
  useFormProblem,
  useAccess,
  useLabel,
  type Tone,
  SettingsCard,
  StickySaveBar,
  useSettingsDraft,
} from '@supportx/ui';

import { ConditionBuilder } from './fields';
import { fromTree, toTree, type Conditions } from './rules';
import { conditionAt, missingProblems, useEditorProblems, whereOf } from './problems';
import { ProblemList } from './ProblemList';
import { TableRegion } from '../../../TableRegion';

const RECORD_TYPE = 'incident';
const STATE_TONE: Record<RoutingOut['state'], Tone> = {
  enabled: 'success',
  draft: 'default',
  disabled: 'warning',
};

/**
 * Admin › Incidents › Routing (WP-029; REQ-RUL-011..014, 018..021): which group a new record
 * goes to, then who in that group. Routing never picks a person; auto-assignment never picks
 * outside the record's group.
 */
export function RoutingTab() {
  const t = useLabel();
  const { message } = App.useApp();
  const { can } = useAccess();
  const editable = can('automation.manage');
  // One save bar for the tab (template E, D-147): the routing settings and the chosen group's
  // assignment are drafts; the routing rules stay a list with their own editor.
  const settings = useRoutingSettings(RECORD_TYPE, can('automation.view'));
  const { saveRoutingSettings } = useAutomationChange();
  const routingSaved = useMemo(
    () => ({
      use_category_group: settings.data?.use_category_group ?? true,
      fallback_group_id: settings.data?.fallback_group_id ?? null,
    }),
    [settings.data],
  );
  const routing = useSettingsDraft(routingSaved);
  const [groupId, setGroupId] = useState<string>();
  const assignment = useGroupAssignment(groupId);
  const assignSaved = useMemo(() => assignment.data ?? EMPTY_ASSIGNMENT, [assignment.data]);
  const assign = useSettingsDraft<AssignmentSettingsOut>(assignSaved);
  const saveAssignment = useSaveGroupAssignment();
  const problem = useFormProblem(); // a refused save, shown above the bar (QA WP-029 BUG-02)
  const pickGroup = (next: string | undefined) => {
    assign.discard(); // edits of one group never carry over to another
    setGroupId(next);
  };
  const save = async () => {
    problem.clear();
    try {
      if (routing.changes > 0 && settings.data !== undefined) {
        await saveRoutingSettings.mutateAsync({
          recordType: RECORD_TYPE,
          version: settings.data.version,
          body: routing.changed,
        });
      }
      if (assign.changes > 0 && assignment.data !== undefined) {
        const { group_id: group, version, ...body } = assign.draft;
        await saveAssignment.mutateAsync({ groupId: group, version, body });
      }
      void message.success(t('common.saved'));
    } catch (error) {
      problem.show(error);
    }
  };
  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Typography.Paragraph type="secondary" style={{ margin: 0, maxWidth: 720 }}>
        {t('automation.routing.explain')}
      </Typography.Paragraph>
      <RoutingSettingsCard
        loading={settings.isPending}
        editable={editable}
        draft={routing.draft}
        set={routing.set}
      />
      <RoutingRules />
      <AssignmentCard
        groupId={groupId}
        onGroup={pickGroup}
        editable={editable}
        draft={assignment.data === undefined ? undefined : assign.draft}
        set={assign.set}
      />
      <FormProblem problem={problem} />
      {editable && (
        <StickySaveBar
          changes={routing.changes + assign.changes}
          saving={saveRoutingSettings.isPending || saveAssignment.isPending}
          onDiscard={() => {
            routing.discard();
            assign.discard();
            problem.clear();
          }}
          onSave={() => void save()}
          testId="routing-save-bar"
        />
      )}
    </Space>
  );
}

const EMPTY_ASSIGNMENT: AssignmentSettingsOut = {
  group_id: '',
  version: 0,
  enabled: false,
  method: 'round_robin',
  load_cap: null,
  on_create: false,
  on_move: false,
  unassigned_only: false,
  count_paused: false,
  record_types: [],
};

function useGroupOptions(keep?: string | null) {
  const t = useLabel();
  const groups = useStructure('groups');
  return {
    loading: groups.isPending,
    options: (groups.data ?? [])
      .filter((g) => !g.disabled || g.id === keep)
      .map((g) => ({ value: g.id, label: g.name })),
    name: (id: string | null | undefined) =>
      // A group not in the list was removed (QA, lane C's #318 note); nothing while it loads.
      groups.data === undefined
        ? ''
        : (groups.data.find((g) => g.id === id)?.name ?? t('automation.group_gone')),
  };
}

/** Category suggestion and the fallback group (none until an admin picks one, D-097). */
interface RoutingSettingsDraft {
  use_category_group: boolean;
  fallback_group_id: string | null;
}

function RoutingSettingsCard({
  loading,
  editable,
  draft,
  set,
}: {
  loading: boolean;
  editable: boolean;
  draft: RoutingSettingsDraft;
  set: (patch: Partial<RoutingSettingsDraft>) => void;
}) {
  const t = useLabel();
  const groups = useGroupOptions(draft.fallback_group_id);
  if (loading) return null;
  return (
    <SettingsCard title={t('automation.routing.settings')} testId="routing-settings">
      <Form layout="vertical" component="div">
        <Form.Item
          label={t('automation.routing.use_category')}
          extra={t('automation.routing.use_category.help')}
        >
          <Switch
            checked={draft.use_category_group}
            disabled={!editable}
            onChange={(use_category_group) => {
              set({ use_category_group });
            }}
            aria-label={t('automation.routing.use_category')}
            data-testid="routing-use-category"
          />
        </Form.Item>
        <Form.Item
          label={t('automation.routing.fallback')}
          extra={t('automation.routing.fallback.help')}
          style={{ marginBottom: 0 }}
        >
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder={t('automation.routing.fallback.none')}
            value={draft.fallback_group_id ?? undefined}
            disabled={!editable}
            loading={groups.loading}
            options={groups.options}
            onChange={(id: string | undefined) => {
              set({ fallback_group_id: id ?? null });
            }}
            style={{ maxWidth: 360, width: '100%' }}
            aria-label={t('automation.routing.fallback')}
            data-testid="routing-fallback"
          />
        </Form.Item>
      </Form>
    </SettingsCard>
  );
}

function RoutingRules() {
  const t = useLabel();
  const { can } = useAccess();
  const editable = can('automation.manage');
  const rules = useRoutingRules(RECORD_TYPE, can('automation.view'));
  const { orderRouting, deleteRouting } = useAutomationChange();
  const groups = useGroupOptions();
  const sites = useStructure('sites');
  const [editing, setEditing] = useState<RoutingOut | 'new'>();
  const list = rules.data ?? [];
  const move = (index: number, by: number) => {
    const ids = list.map((r) => r.id);
    const [moved] = ids.splice(index, 1);
    if (moved === undefined) return;
    ids.splice(index + by, 0, moved);
    orderRouting.mutate({ record_type: RECORD_TYPE, ids }, { onError: reportError });
  };
  return (
    <Card
      size="small"
      title={t('automation.routing.rules')}
      extra={
        editable && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing('new');
            }}
            data-testid="routing-add"
          >
            {t('automation.routing.add')}
          </Button>
        )
      }
    >
      {/* A keyboard can reach and scroll the table's own scroll box (QA V-18, axe). */}
      <TableRegion label={t('automation.routing.rules')}>
        <Table<RoutingOut>
          rowKey="id"
          loading={rules.isPending}
          dataSource={list}
          pagination={false}
          data-testid="routing-table"
          locale={{
            emptyText: (
              <Typography.Text type="secondary">{t('automation.routing.none')}</Typography.Text>
            ),
          }}
          onRow={(rule) => ({
            onClick: () => {
              if (editable) setEditing(rule);
            },
            style: editable ? { cursor: 'pointer' } : undefined,
            'data-testid': `routing-row-${rule.name}`,
          })}
          columns={[
            {
              key: 'order',
              title: t('automation.col.order'),
              width: 120,
              render: (_, rule, index) => (
                <Flex gap={4} align="center">
                  <span>{index + 1}</span>
                  {editable && (
                    <>
                      <Button
                        size="small"
                        icon={<ArrowUpOutlined />}
                        aria-label={t('automation.move_up', { name: rule.name })}
                        disabled={index === 0 || orderRouting.isPending}
                        onClick={(event) => {
                          event.stopPropagation();
                          move(index, -1);
                        }}
                      />
                      <Button
                        size="small"
                        icon={<ArrowDownOutlined />}
                        aria-label={t('automation.move_down', { name: rule.name })}
                        disabled={index === list.length - 1 || orderRouting.isPending}
                        onClick={(event) => {
                          event.stopPropagation();
                          move(index, 1);
                        }}
                      />
                    </>
                  )}
                </Flex>
              ),
            },
            {
              key: 'name',
              title: t('automation.col.name'),
              render: (_, rule) => <bdi>{rule.name}</bdi>,
            },
            {
              key: 'group',
              title: t('automation.col.group'),
              render: (_, rule) => <bdi>{groups.name(rule.group_id)}</bdi>,
            },
            {
              key: 'site',
              title: t('automation.col.site'),
              render: (_, rule) =>
                rule.site_id === null ? (
                  t('automation.routing.any_site')
                ) : (
                  <bdi>
                    {sites.data === undefined
                      ? ''
                      : (sites.data.find((s) => s.id === rule.site_id)?.name ??
                        t('automation.site_gone'))}
                  </bdi>
                ),
            },
            {
              key: 'state',
              title: t('automation.col.state'),
              render: (_, rule) => (
                <ToneTag tone={STATE_TONE[rule.state]}>{t(`rule_state.${rule.state}`)}</ToneTag>
              ),
            },
            ...(editable
              ? [
                  {
                    key: 'actions',
                    title: <span className="sr-only">{t('automation.col.actions')}</span>,
                    render: (_: unknown, rule: RoutingOut) => (
                      <Popconfirm
                        title={t('automation.remove.confirm', { name: rule.name })}
                        okText={t('automation.remove')}
                        cancelText={t('actions.cancel')}
                        onConfirm={() => {
                          deleteRouting.mutate(
                            { id: rule.id, version: rule.version },
                            { onError: reportError },
                          );
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
                          data-testid={`routing-remove-${rule.name}`}
                        >
                          {t('automation.remove')}
                        </Button>
                      </Popconfirm>
                    ),
                  },
                ]
              : []),
          ]}
        />
      </TableRegion>
      <RoutingEditor
        rule={editing === 'new' ? undefined : editing}
        open={editing !== undefined}
        latest={
          editing === 'new' || editing === undefined
            ? undefined
            : list.find((r) => r.id === editing.id)
        }
        onClose={() => {
          setEditing(undefined);
        }}
      />
    </Card>
  );
}

interface RoutingDraft {
  name: string;
  conditions: Conditions;
  site_id: string | null;
  group_id: string | null;
  overwrite: boolean;
  state: RoutingOut['state'];
}

function routingDraftOf(rule: RoutingOut | undefined): RoutingDraft {
  if (rule === undefined) {
    return {
      name: '',
      conditions: { join: 'and', rows: [] },
      site_id: null,
      group_id: null,
      overwrite: false,
      state: 'draft',
    };
  }
  return {
    name: rule.name,
    conditions: fromTree(rule.conditions),
    site_id: rule.site_id,
    group_id: rule.group_id,
    overwrite: rule.overwrite,
    state: rule.state,
  };
}

function RoutingEditor({
  rule,
  latest,
  open,
  onClose,
}: {
  rule: RoutingOut | undefined;
  latest: RoutingOut | undefined;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const fields = useRuleFields(RECORD_TYPE, open);
  const sites = useStructure('sites', open);
  const { createRouting, updateRouting } = useAutomationChange();
  const [draft, setDraft] = useState<RoutingDraft>(() => routingDraftOf(rule));
  const [opened, setOpened] = useState<string | undefined>(rule?.id);
  const [version, setVersion] = useState(rule?.version);
  const issues = useEditorProblems();
  const { problems } = issues;
  // A refusal with no problem list (a rule, a limit) is shown here (QA WP-029 BUG-02).
  const problem = useFormProblem();
  const [conflict, setConflict] = useState<unknown>();
  const groups = useGroupOptions(draft.group_id);
  if (open && opened !== (rule?.id ?? 'new')) {
    setOpened(rule?.id ?? 'new');
    setDraft(routingDraftOf(rule));
    setVersion(rule?.version);
    issues.clear();
    problem.clear();
  }
  const stale = latest !== undefined && version !== undefined && latest.version !== version;
  const edit = (next: Partial<RoutingDraft>) => {
    setDraft({ ...draft, ...next });
    issues.clear();
  };
  const failed = (error: unknown) => {
    if (error instanceof ApiError && error.isConflict) {
      setConflict(error);
      return;
    }
    // Each problem at its field, named and marked (QA WP-029 BUG-03).
    if (issues.take(error)) markHandled(error);
    else problem.show(error);
  };
  const save = (at = version) => {
    problem.clear();
    const done = () => {
      void message.success(t('common.saved'));
      onClose();
    };
    if (issues.check(missingProblems(t, { name: draft.name, group_id: draft.group_id }))) return;
    const body = {
      name: draft.name,
      conditions: toTree(draft.conditions),
      site_id: draft.site_id,
      overwrite: draft.overwrite,
      state: draft.state,
    };
    if (rule === undefined) {
      createRouting.mutate(
        { ...body, group_id: draft.group_id ?? '', record_type: RECORD_TYPE },
        { onSuccess: done, onError: failed },
      );
    } else {
      updateRouting.mutate(
        { id: rule.id, version: at ?? rule.version, body: { ...body, group_id: draft.group_id } },
        { onSuccess: done, onError: failed },
      );
    }
  };
  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={720}
      destroyOnHidden
      title={rule === undefined ? t('automation.routing.add') : t('automation.routing.edit')}
      data-testid="routing-editor"
    >
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {stale && <Alert type="warning" showIcon message={t('organization.changed_elsewhere')} />}
        <FormProblem problem={problem} />
        <ProblemList problems={problems} testId="routing-problems" />
        <Form layout="vertical">
          <Form.Item
            label={t('automation.field_name')}
            validateStatus={issues.status('name')}
            htmlFor="routing-name"
            required
          >
            <Input
              id="routing-name"
              value={draft.name}
              onChange={(event) => {
                edit({ name: event.target.value });
              }}
              count={lengthLimit(200)}
              data-testid="routing-name"
            />
          </Form.Item>
          <Form.Item
            label={t('automation.field_conditions')}
            validateStatus={issues.status('conditions')}
          >
            <ConditionBuilder
              invalid={(index) => conditionAt(problems, index)}
              fields={fields.data ?? []}
              value={draft.conditions}
              onChange={(conditions) => {
                edit({ conditions });
              }}
            />
          </Form.Item>
          <Form.Item
            label={t('automation.routing.field_site')}
            validateStatus={issues.status('site_id')}
            extra={t('automation.routing.field_site.help')}
          >
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder={t('automation.routing.any_site')}
              value={draft.site_id ?? undefined}
              onChange={(id: string | undefined) => {
                edit({ site_id: id ?? null });
              }}
              options={(sites.data ?? [])
                .filter((s) => !s.disabled || s.id === draft.site_id)
                .map((s) => ({ value: s.id, label: s.name }))}
              style={{ maxWidth: 360 }}
              aria-label={t('automation.routing.field_site')}
              data-testid="routing-site"
            />
          </Form.Item>
          <Form.Item
            label={t('automation.routing.field_group')}
            validateStatus={issues.status('group_id')}
            required
          >
            <Select
              showSearch
              optionFilterProp="label"
              value={draft.group_id ?? undefined}
              onChange={(id: string) => {
                edit({ group_id: id });
              }}
              options={groups.options}
              style={{ maxWidth: 360 }}
              aria-label={t('automation.routing.field_group')}
              data-testid="routing-group"
            />
          </Form.Item>
          <Flex gap={32} wrap>
            <Form.Item
              label={t('automation.routing.field_overwrite')}
              validateStatus={issues.status('overwrite')}
              extra={t('automation.routing.field_overwrite.help')}
            >
              <Switch
                checked={draft.overwrite}
                onChange={(overwrite) => {
                  edit({ overwrite });
                }}
                aria-label={t('automation.routing.field_overwrite')}
                data-testid="routing-overwrite"
              />
            </Form.Item>
            <Form.Item
              label={t('automation.field_state')}
              validateStatus={issues.status('state')}
              extra={t('automation.field_state.help')}
            >
              <Select
                value={draft.state}
                onChange={(state: RoutingOut['state']) => {
                  edit({ state });
                }}
                options={(['draft', 'enabled', 'disabled'] as const).map((s) => ({
                  value: s,
                  label: t(`rule_state.${s}`),
                }))}
                style={{ minWidth: 160 }}
                aria-label={t('automation.field_state')}
                data-testid="routing-state"
              />
            </Form.Item>
          </Flex>
        </Form>
        <Button
          type="primary"
          onClick={() => {
            save();
          }}
          loading={createRouting.isPending || updateRouting.isPending}
          data-testid="routing-save"
        >
          {t('actions.save')}
        </Button>
      </Space>
      <ConflictDialog
        open={conflict !== undefined}
        error={conflict}
        fieldLabel={(field) => whereOf(t, field)}
        opened={rule}
        latest={latest}
        onReload={() => {
          setConflict(undefined);
          onClose();
        }}
        onKeepMine={() => {
          setConflict(undefined);
          if (latest === undefined) return;
          setVersion(latest.version);
          save(latest.version);
        }}
      />
    </Drawer>
  );
}

/** A group's auto-assignment: off by default; only its members, only Available ones. */
function AssignmentCard({
  groupId,
  onGroup,
  editable,
  draft,
  set,
}: {
  groupId: string | undefined;
  onGroup: (groupId: string | undefined) => void;
  editable: boolean;
  draft: AssignmentSettingsOut | undefined;
  set: (patch: Partial<AssignmentSettingsOut>) => void;
}) {
  const t = useLabel();
  const groups = useGroupOptions();
  return (
    <SettingsCard
      title={t('automation.assign.title')}
      description={t('automation.assign.explain')}
      testId="assign-card"
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        <Select
          showSearch
          optionFilterProp="label"
          placeholder={t('automation.assign.pick_group')}
          value={groupId}
          onChange={onGroup}
          options={groups.options}
          loading={groups.loading}
          style={{ maxWidth: 360, width: '100%' }}
          aria-label={t('automation.assign.pick_group')}
          data-testid="assign-group"
        />
        {draft !== undefined && <AssignmentForm draft={draft} set={set} disabled={!editable} />}
      </Space>
    </SettingsCard>
  );
}

function AssignmentForm({
  draft,
  set,
  disabled,
}: {
  draft: AssignmentSettingsOut;
  set: (patch: Partial<AssignmentSettingsOut>) => void;
  disabled: boolean;
}) {
  const t = useLabel();
  return (
    <Form layout="vertical" component="div" data-testid="assign-form">
      <Flex gap={32} wrap>
        <Form.Item label={t('automation.assign.enabled')}>
          <Switch
            checked={draft.enabled}
            disabled={disabled}
            onChange={(enabled) => {
              set({ enabled });
            }}
            aria-label={t('automation.assign.enabled')}
            data-testid="assign-enabled"
          />
        </Form.Item>
        <Form.Item label={t('automation.assign.method')}>
          <Select
            value={draft.method}
            disabled={disabled}
            onChange={(method: AssignmentSettingsOut['method']) => {
              set({ method });
            }}
            options={(['round_robin', 'load_balancing'] as const).map((m) => ({
              value: m,
              label: t(`assign_method.${m}`),
            }))}
            style={{ minWidth: 200 }}
            aria-label={t('automation.assign.method')}
            data-testid="assign-method"
          />
        </Form.Item>
        <Form.Item
          label={t('automation.assign.load_cap')}
          extra={t('automation.assign.load_cap.help')}
        >
          <InputNumber
            min={1}
            max={999}
            value={draft.load_cap}
            disabled={disabled}
            onChange={(load_cap) => {
              set({ load_cap });
            }}
            aria-label={t('automation.assign.load_cap')}
            data-testid="assign-load-cap"
          />
        </Form.Item>
      </Flex>
      <Flex gap={32} wrap>
        {(['on_create', 'on_move', 'unassigned_only', 'count_paused'] as const).map((key) => (
          <Form.Item key={key} label={t(`automation.assign.${key}`)}>
            <Switch
              checked={draft[key]}
              disabled={disabled}
              onChange={(on) => {
                set({ [key]: on });
              }}
              aria-label={t(`automation.assign.${key}`)}
              data-testid={`assign-${key}`}
            />
          </Form.Item>
        ))}
      </Flex>
    </Form>
  );
}
