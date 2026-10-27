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
import { useState } from 'react';

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
  ConflictDialog,
  ToneTag,
  lengthLimit,
  reportError,
  useAccess,
  useLabel,
  type Tone,
} from '@supportx/ui';

import { ConditionBuilder } from './fields';
import { fromTree, problemsOf, toTree, type Conditions } from './rules';

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
  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Typography.Paragraph type="secondary" style={{ margin: 0, maxWidth: 720 }}>
        {t('automation.routing.explain')}
      </Typography.Paragraph>
      <RoutingSettingsCard />
      <RoutingRules />
      <AssignmentCard />
    </Space>
  );
}

function useGroupOptions(keep?: string | null) {
  const groups = useStructure('groups');
  return {
    loading: groups.isPending,
    options: (groups.data ?? [])
      .filter((g) => !g.disabled || g.id === keep)
      .map((g) => ({ value: g.id, label: g.name })),
    name: (id: string | null | undefined) =>
      groups.data?.find((g) => g.id === id)?.name ?? t_unknown,
  };
}
const t_unknown = '—';

/** Category suggestion and the fallback group (none until an admin picks one, D-097). */
function RoutingSettingsCard() {
  const t = useLabel();
  const { message } = App.useApp();
  const { can } = useAccess();
  const editable = can('automation.manage');
  const settings = useRoutingSettings(RECORD_TYPE, can('automation.view'));
  const { saveRoutingSettings } = useAutomationChange();
  const groups = useGroupOptions(settings.data?.fallback_group_id);
  const save = (body: { fallback_group_id?: string | null; use_category_group?: boolean }) => {
    if (settings.data === undefined) return;
    saveRoutingSettings.mutate(
      { recordType: RECORD_TYPE, version: settings.data.version, body },
      {
        onSuccess: () => void message.success(t('common.saved')),
        onError: reportError,
      },
    );
  };
  return (
    <Card title={t('automation.routing.settings')} loading={settings.isPending} size="small">
      <Form layout="vertical">
        <Form.Item
          label={t('automation.routing.use_category')}
          extra={t('automation.routing.use_category.help')}
        >
          <Switch
            checked={settings.data?.use_category_group ?? true}
            disabled={!editable || saveRoutingSettings.isPending}
            onChange={(use_category_group) => {
              save({ use_category_group });
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
            value={settings.data?.fallback_group_id ?? undefined}
            disabled={!editable || saveRoutingSettings.isPending}
            loading={groups.loading}
            options={groups.options}
            onChange={(id: string | undefined) => {
              save({ fallback_group_id: id ?? null });
            }}
            style={{ maxWidth: 360, width: '100%' }}
            aria-label={t('automation.routing.fallback')}
            data-testid="routing-fallback"
          />
        </Form.Item>
      </Form>
    </Card>
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
      <Table<RoutingOut>
        rowKey="id"
        loading={rules.isPending}
        dataSource={list}
        pagination={false}
        data-testid="routing-table"
        locale={{ emptyText: t('automation.routing.none') }}
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
                <bdi>{sites.data?.find((s) => s.id === rule.site_id)?.name ?? t_unknown}</bdi>
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
  const [problems, setProblems] = useState<string[]>([]);
  const [conflict, setConflict] = useState<unknown>();
  const groups = useGroupOptions(draft.group_id);
  if (open && opened !== (rule?.id ?? 'new')) {
    setOpened(rule?.id ?? 'new');
    setDraft(routingDraftOf(rule));
    setVersion(rule?.version);
    setProblems([]);
  }
  const stale = latest !== undefined && version !== undefined && latest.version !== version;
  const edit = (next: Partial<RoutingDraft>) => {
    setDraft({ ...draft, ...next });
    setProblems([]);
  };
  const failed = (error: unknown) => {
    if (error instanceof ApiError && error.isConflict) {
      setConflict(error);
      return;
    }
    const found = problemsOf(t, error);
    if (found.length > 0) setProblems(found);
    else reportError(error);
  };
  const save = (at = version) => {
    const done = () => {
      void message.success(t('common.saved'));
      onClose();
    };
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
        {problems.length > 0 && (
          <Alert
            type="error"
            showIcon
            data-testid="routing-problems"
            message={t('automation.problems')}
            description={
              <ul style={{ margin: 0 }}>
                {problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            }
          />
        )}
        <Form layout="vertical">
          <Form.Item label={t('automation.field_name')} required>
            <Input
              value={draft.name}
              onChange={(event) => {
                edit({ name: event.target.value });
              }}
              count={lengthLimit(200)}
              data-testid="routing-name"
            />
          </Form.Item>
          <Form.Item label={t('automation.field_conditions')}>
            <ConditionBuilder
              fields={fields.data ?? []}
              value={draft.conditions}
              onChange={(conditions) => {
                edit({ conditions });
              }}
            />
          </Form.Item>
          <Form.Item
            label={t('automation.routing.field_site')}
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
          <Form.Item label={t('automation.routing.field_group')} required>
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
            <Form.Item label={t('automation.field_state')} extra={t('automation.field_state.help')}>
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
        fieldLabel={(field) => t(`automation.field_${field}`)}
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
function AssignmentCard() {
  const t = useLabel();
  const [groupId, setGroupId] = useState<string>();
  const groups = useGroupOptions();
  const settings = useGroupAssignment(groupId);
  return (
    <Card size="small" title={t('automation.assign.title')}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Typography.Text type="secondary">{t('automation.assign.explain')}</Typography.Text>
        <Select
          showSearch
          optionFilterProp="label"
          placeholder={t('automation.assign.pick_group')}
          value={groupId}
          onChange={setGroupId}
          options={groups.options}
          loading={groups.loading}
          style={{ maxWidth: 360, width: '100%' }}
          aria-label={t('automation.assign.pick_group')}
          data-testid="assign-group"
        />
        {settings.data !== undefined && (
          <AssignmentForm
            key={`${settings.data.group_id}:${String(settings.data.version)}`}
            settings={settings.data}
          />
        )}
      </Space>
    </Card>
  );
}

function AssignmentForm({ settings }: { settings: AssignmentSettingsOut }) {
  const t = useLabel();
  const { message } = App.useApp();
  const { can } = useAccess();
  const editable = can('automation.manage');
  const save = useSaveGroupAssignment();
  const [draft, setDraft] = useState(settings);
  const disabled = !editable || save.isPending;
  return (
    <Form layout="vertical" data-testid="assign-form">
      <Flex gap={32} wrap>
        <Form.Item label={t('automation.assign.enabled')}>
          <Switch
            checked={draft.enabled}
            disabled={disabled}
            onChange={(enabled) => {
              setDraft({ ...draft, enabled });
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
              setDraft({ ...draft, method });
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
              setDraft({ ...draft, load_cap });
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
                setDraft({ ...draft, [key]: on });
              }}
              aria-label={t(`automation.assign.${key}`)}
              data-testid={`assign-${key}`}
            />
          </Form.Item>
        ))}
      </Flex>
      {editable && (
        <Button
          type="primary"
          loading={save.isPending}
          onClick={() => {
            const { group_id: groupId, version, ...body } = draft;
            save.mutate(
              { groupId, version, body },
              {
                onSuccess: () => void message.success(t('common.saved')),
                onError: reportError,
              },
            );
          }}
          data-testid="assign-save"
        >
          {t('actions.save')}
        </Button>
      )}
    </Form>
  );
}
