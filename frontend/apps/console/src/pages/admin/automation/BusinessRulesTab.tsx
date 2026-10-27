import { ArrowDownOutlined, ArrowUpOutlined, PlusOutlined } from '@ant-design/icons';
import {
  Alert,
  App,
  Button,
  Checkbox,
  Drawer,
  Flex,
  Form,
  Input,
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
  useBusinessRules,
  useRuleFields,
  type RuleActionIO,
  type RuleFieldOut,
  type RuleOut,
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

import { ConditionBuilder, ValueInput } from './fields';
import { fromTree, problemsOf, toTree, useFieldName, type Conditions } from './rules';

const RECORD_TYPE = 'incident';
const STATE_TONE: Record<RuleOut['state'], Tone> = {
  enabled: 'success',
  draft: 'default',
  disabled: 'warning',
};
const LANGUAGES = ['en', 'ar', 'ur'] as const;

/**
 * Admin › Incidents › Business rules (WP-029; REQ-RUL-001..005, 029): rules run inside the save
 * in this order; "stop after this rule" ends the run when it matches; drafts never run.
 */
export function BusinessRulesTab() {
  const t = useLabel();
  const { can } = useAccess();
  const editable = can('automation.manage');
  const rules = useBusinessRules(RECORD_TYPE, can('automation.view'));
  const { orderRules, deleteRule } = useAutomationChange();
  const [editing, setEditing] = useState<RuleOut | 'new'>();
  const list = rules.data ?? [];
  const move = (index: number, by: number) => {
    const ids = list.map((r) => r.id);
    const [moved] = ids.splice(index, 1);
    if (moved === undefined) return;
    ids.splice(index + by, 0, moved);
    orderRules.mutate({ record_type: RECORD_TYPE, ids }, { onError: reportError });
  };
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Flex justify="space-between" align="baseline" wrap gap={8}>
        <Typography.Paragraph type="secondary" style={{ margin: 0, maxWidth: 720 }}>
          {t('automation.rules.explain')}
        </Typography.Paragraph>
        {editable && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing('new');
            }}
            data-testid="rule-add"
          >
            {t('automation.rules.add')}
          </Button>
        )}
      </Flex>
      <Table<RuleOut>
        rowKey="id"
        loading={rules.isPending}
        dataSource={list}
        pagination={false}
        data-testid="rules-table"
        locale={{ emptyText: t('automation.rules.none') }}
        onRow={(rule) => ({
          onClick: () => {
            if (editable) setEditing(rule);
          },
          style: editable ? { cursor: 'pointer' } : undefined,
          'data-testid': `rule-row-${rule.name}`,
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
                      disabled={index === 0 || orderRules.isPending}
                      onClick={(event) => {
                        event.stopPropagation();
                        move(index, -1);
                      }}
                    />
                    <Button
                      size="small"
                      icon={<ArrowDownOutlined />}
                      aria-label={t('automation.move_down', { name: rule.name })}
                      disabled={index === list.length - 1 || orderRules.isPending}
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
            render: (_, rule) => (
              <Flex gap={6} wrap align="center">
                <bdi>{rule.name}</bdi>
                {rule.stop_after && (
                  <ToneTag tone="purple" testId="rule-stop-marker">
                    {t('automation.stop_marker')}
                  </ToneTag>
                )}
              </Flex>
            ),
          },
          {
            key: 'events',
            title: t('automation.col.events'),
            render: (_, rule) =>
              rule.events.map((e) => t(`rule_event.${e}`)).join(t('list.separator')),
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
                  render: (_: unknown, rule: RuleOut) => (
                    <Popconfirm
                      title={t('automation.remove.confirm', { name: rule.name })}
                      okText={t('automation.remove')}
                      cancelText={t('actions.cancel')}
                      onConfirm={() => {
                        deleteRule.mutate(
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
                        data-testid={`rule-remove-${rule.name}`}
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
      <RuleEditor
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
    </Space>
  );
}

interface Draft {
  name: string;
  description: string;
  events: RuleOut['events'];
  conditions: Conditions;
  actions: RuleActionIO[];
  stop_after: boolean;
  state: RuleOut['state'];
}

function draftOf(rule: RuleOut | undefined): Draft {
  if (rule === undefined) {
    return {
      name: '',
      description: '',
      events: ['create'],
      conditions: { join: 'and', rows: [] },
      actions: [{ kind: 'set', field: null, value: null, mode: 'fill_empty' }],
      stop_after: false,
      state: 'draft',
    };
  }
  return {
    name: rule.name,
    description: rule.description ?? '',
    events: rule.events,
    conditions: fromTree(rule.conditions),
    actions: rule.actions,
    stop_after: rule.stop_after,
    state: rule.state,
  };
}

/** Add or change a rule. Keeps the version it opened: a save elsewhere shows the conflict. */
function RuleEditor({
  rule,
  latest,
  open,
  onClose,
}: {
  rule: RuleOut | undefined;
  latest: RuleOut | undefined;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const fields = useRuleFields(RECORD_TYPE, open);
  const { createRule, updateRule } = useAutomationChange();
  const [draft, setDraft] = useState<Draft>(() => draftOf(rule));
  const [opened, setOpened] = useState<string | undefined>(rule?.id);
  const [version, setVersion] = useState(rule?.version);
  const [problems, setProblems] = useState<string[]>([]);
  const [conflict, setConflict] = useState<unknown>();
  if (open && opened !== (rule?.id ?? 'new')) {
    setOpened(rule?.id ?? 'new');
    setDraft(draftOf(rule));
    setVersion(rule?.version);
    setProblems([]);
  }
  const stale = latest !== undefined && version !== undefined && latest.version !== version;
  const edit = (next: Partial<Draft>) => {
    setDraft({ ...draft, ...next });
    setProblems([]);
  };
  const body = () => ({
    name: draft.name,
    description: draft.description.trim() === '' ? null : draft.description,
    events: draft.events,
    conditions: toTree(draft.conditions),
    actions: draft.actions,
    stop_after: draft.stop_after,
    state: draft.state,
  });
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
    if (rule === undefined) {
      createRule.mutate(
        { ...body(), record_type: RECORD_TYPE },
        { onSuccess: done, onError: failed },
      );
    } else {
      updateRule.mutate(
        { id: rule.id, version: at ?? rule.version, body: body() },
        { onSuccess: done, onError: failed },
      );
    }
  };
  const all = fields.data ?? [];
  const settable = all.filter((f) => f.settable);
  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={720}
      destroyOnHidden
      title={rule === undefined ? t('automation.rules.add') : t('automation.rules.edit')}
      data-testid="rule-editor"
    >
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {stale && <Alert type="warning" showIcon message={t('organization.changed_elsewhere')} />}
        {problems.length > 0 && (
          <Alert
            type="error"
            showIcon
            data-testid="rule-problems"
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
              data-testid="rule-name"
            />
          </Form.Item>
          <Form.Item label={t('automation.field_description')}>
            <Input.TextArea
              rows={2}
              value={draft.description}
              onChange={(event) => {
                edit({ description: event.target.value });
              }}
              count={lengthLimit(2000)}
            />
          </Form.Item>
          <Form.Item label={t('automation.field_events')} required>
            <Checkbox.Group
              value={draft.events}
              onChange={(next) => {
                edit({ events: next });
              }}
              options={(['create', 'update'] as const).map((e) => ({
                value: e,
                label: t(`rule_event.${e}`),
              }))}
              data-testid="rule-events"
            />
          </Form.Item>
          <Form.Item label={t('automation.field_conditions')}>
            <ConditionBuilder
              fields={all}
              value={draft.conditions}
              onChange={(conditions) => {
                edit({ conditions });
              }}
            />
          </Form.Item>
          <Form.Item label={t('automation.field_actions')} required>
            <ActionsEditor
              fields={settable}
              actions={draft.actions}
              onChange={(actions) => {
                edit({ actions });
              }}
            />
          </Form.Item>
          <Flex gap={32} wrap>
            <Form.Item
              label={t('automation.field_stop_after')}
              extra={t('automation.field_stop_after.help')}
            >
              <Switch
                checked={draft.stop_after}
                onChange={(stop_after) => {
                  edit({ stop_after });
                }}
                aria-label={t('automation.field_stop_after')}
                data-testid="rule-stop-after"
              />
            </Form.Item>
            <Form.Item label={t('automation.field_state')} extra={t('automation.field_state.help')}>
              <Select
                value={draft.state}
                onChange={(state: RuleOut['state']) => {
                  edit({ state });
                }}
                options={(['draft', 'enabled', 'disabled'] as const).map((s) => ({
                  value: s,
                  label: t(`rule_state.${s}`),
                }))}
                style={{ minWidth: 160 }}
                aria-label={t('automation.field_state')}
                data-testid="rule-state"
              />
            </Form.Item>
          </Flex>
        </Form>
        <Button
          type="primary"
          onClick={() => {
            save();
          }}
          loading={createRule.isPending || updateRule.isPending}
          data-testid="rule-save"
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

/** "Set a field" or "Refuse the save" actions, in order. */
function ActionsEditor({
  fields,
  actions,
  onChange,
}: {
  fields: RuleFieldOut[];
  actions: RuleActionIO[];
  onChange: (next: RuleActionIO[]) => void;
}) {
  const t = useLabel();
  const name = useFieldName();
  const byName = new Map(fields.map((f) => [f.name, f]));
  const update = (index: number, next: RuleActionIO) => {
    onChange(actions.map((a, i) => (i === index ? next : a)));
  };
  return (
    <Space direction="vertical" style={{ width: '100%' }} data-testid="rule-actions">
      {actions.map((action, index) => {
        const field = action.field != null ? byName.get(action.field) : undefined;
        return (
          // Actions have no ID: they are edited in place.
          <Flex key={index} gap={8} wrap align="center" data-testid={`action-${String(index)}`}>
            <Select
              aria-label={t('automation.action_kind')}
              value={action.kind}
              onChange={(kind: RuleActionIO['kind']) => {
                update(
                  index,
                  kind === 'set'
                    ? { kind, field: null, value: null, mode: 'fill_empty' }
                    : { kind, message: { en: '' }, mode: 'fill_empty' },
                );
              }}
              options={(['set', 'refuse'] as const).map((k) => ({
                value: k,
                label: t(`rule_action_kind.${k}`),
              }))}
              style={{ minWidth: 160 }}
              data-testid={`action-${String(index)}-kind`}
            />
            {action.kind === 'set' ? (
              <>
                <Select
                  aria-label={t('automation.conditions.field')}
                  showSearch
                  optionFilterProp="label"
                  value={action.field ?? undefined}
                  placeholder={t('automation.conditions.field')}
                  onChange={(next: string) => {
                    update(index, { ...action, field: next, value: null });
                  }}
                  options={fields.map((f) => ({ value: f.name, label: name(f.name) }))}
                  style={{ minWidth: 200 }}
                  data-testid={`action-${String(index)}-field`}
                />
                {field !== undefined && (
                  <ValueInput
                    field={field}
                    value={action.value}
                    onChange={(value) => {
                      update(index, { ...action, value });
                    }}
                    testId={`action-${String(index)}-value`}
                    ariaLabel={t('automation.conditions.value')}
                  />
                )}
                <Select
                  aria-label={t('automation.action_mode')}
                  value={action.mode}
                  onChange={(mode: RuleActionIO['mode']) => {
                    update(index, { ...action, mode });
                  }}
                  options={(['fill_empty', 'overwrite'] as const).map((m) => ({
                    value: m,
                    label: t(`rule_action_mode.${m}`),
                  }))}
                  style={{ minWidth: 200 }}
                  data-testid={`action-${String(index)}-mode`}
                />
              </>
            ) : (
              <Space direction="vertical" style={{ flex: 1, minWidth: 260 }}>
                {LANGUAGES.map((language) => (
                  <Input
                    key={language}
                    dir={language === 'en' ? 'ltr' : 'rtl'}
                    prefix={
                      <Typography.Text type="secondary">{t(`locale.${language}`)}</Typography.Text>
                    }
                    value={action.message?.[language] ?? ''}
                    onChange={(event) => {
                      update(index, {
                        ...action,
                        message: { ...(action.message ?? {}), [language]: event.target.value },
                      });
                    }}
                    count={lengthLimit(500)}
                    aria-label={t('automation.refusal_message', {
                      language: t(`locale.${language}`),
                    })}
                    data-testid={`action-${String(index)}-message-${language}`}
                  />
                ))}
              </Space>
            )}
            <Button
              aria-label={t('automation.action_remove')}
              onClick={() => {
                onChange(actions.filter((_, i) => i !== index));
              }}
            >
              {t('automation.remove')}
            </Button>
          </Flex>
        );
      })}
      <Button
        icon={<PlusOutlined />}
        onClick={() => {
          onChange([...actions, { kind: 'set', field: null, value: null, mode: 'fill_empty' }]);
        }}
        data-testid="action-add"
      >
        {t('automation.action_add')}
      </Button>
    </Space>
  );
}
