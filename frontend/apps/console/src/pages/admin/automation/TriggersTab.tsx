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
  useRuleFields,
  useTriggers,
  type TriggerActionIO,
  type TriggerOut,
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

import { AfterActions } from './AfterActions';
import { ConditionBuilder } from './fields';
import { emptyAction, fromTree, problemsOf, toTree, triggerOp, type Conditions } from './rules';

const RECORD_TYPE = 'incident';
const EVENTS = [
  'created',
  'updated',
  'status_changed',
  'assigned',
  'note_added',
  'requester_replied',
] as const;
const STATE_TONE: Record<TriggerOut['state'], Tone> = {
  enabled: 'success',
  draft: 'default',
  disabled: 'warning',
};

/**
 * Admin › Incidents › Triggers (WP-029 part 2; REQ-RUL-009, 010, 028): they run after a change
 * is saved, from its event, in this order. Each action's outcome shows on the record; a loop
 * stops at a clear limit and says which triggers took part.
 */
export function TriggersTab() {
  const t = useLabel();
  const { can } = useAccess();
  const editable = can('automation.manage');
  const triggers = useTriggers(RECORD_TYPE, can('automation.view'));
  const { orderTriggers, deleteTrigger } = useAutomationChange();
  const [editing, setEditing] = useState<TriggerOut | 'new'>();
  const list = triggers.data ?? [];
  const move = (index: number, by: number) => {
    const ids = list.map((r) => r.id);
    const [moved] = ids.splice(index, 1);
    if (moved === undefined) return;
    ids.splice(index + by, 0, moved);
    orderTriggers.mutate({ record_type: RECORD_TYPE, ids }, { onError: reportError });
  };
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Flex justify="space-between" align="baseline" wrap gap={8}>
        <Typography.Paragraph type="secondary" style={{ margin: 0, maxWidth: 720 }}>
          {t('automation.triggers.explain')}
        </Typography.Paragraph>
        {editable && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing('new');
            }}
            data-testid="trigger-add"
          >
            {t('automation.triggers.add')}
          </Button>
        )}
      </Flex>
      <Table<TriggerOut>
        rowKey="id"
        loading={triggers.isPending}
        dataSource={list}
        pagination={false}
        data-testid="triggers-table"
        locale={{
          emptyText: (
            <Typography.Text type="secondary">{t('automation.triggers.none')}</Typography.Text>
          ),
        }}
        onRow={(trigger) => ({
          onClick: () => {
            if (editable) setEditing(trigger);
          },
          style: editable ? { cursor: 'pointer' } : undefined,
          'data-testid': `trigger-row-${trigger.name}`,
        })}
        columns={[
          {
            key: 'order',
            title: t('automation.col.order'),
            width: 120,
            render: (_, trigger, index) => (
              <Flex gap={4} align="center">
                <span>{index + 1}</span>
                {editable && (
                  <>
                    <Button
                      size="small"
                      icon={<ArrowUpOutlined />}
                      aria-label={t('automation.move_up', { name: trigger.name })}
                      disabled={index === 0 || orderTriggers.isPending}
                      onClick={(event) => {
                        event.stopPropagation();
                        move(index, -1);
                      }}
                    />
                    <Button
                      size="small"
                      icon={<ArrowDownOutlined />}
                      aria-label={t('automation.move_down', { name: trigger.name })}
                      disabled={index === list.length - 1 || orderTriggers.isPending}
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
            render: (_, trigger) => <bdi>{trigger.name}</bdi>,
          },
          {
            key: 'events',
            title: t('automation.col.events'),
            render: (_, trigger) =>
              trigger.events.map((e) => t(`trigger_event.${e}`)).join(t('list.separator')),
          },
          {
            key: 'state',
            title: t('automation.col.state'),
            render: (_, trigger) => (
              <ToneTag tone={STATE_TONE[trigger.state]}>{t(`rule_state.${trigger.state}`)}</ToneTag>
            ),
          },
          ...(editable
            ? [
                {
                  key: 'actions',
                  title: <span className="sr-only">{t('automation.col.actions')}</span>,
                  render: (_: unknown, trigger: TriggerOut) => (
                    <Popconfirm
                      title={t('automation.remove.confirm', { name: trigger.name })}
                      okText={t('automation.remove')}
                      cancelText={t('actions.cancel')}
                      onConfirm={() => {
                        deleteTrigger.mutate(
                          { id: trigger.id, version: trigger.version },
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
                        data-testid={`trigger-remove-${trigger.name}`}
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
      <TriggerEditor
        trigger={editing === 'new' ? undefined : editing}
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
  events: TriggerOut['events'];
  conditions: Conditions;
  actions: TriggerActionIO[];
  fire_on_own_change: boolean;
  state: TriggerOut['state'];
}

function draftOf(trigger: TriggerOut | undefined): Draft {
  if (trigger === undefined) {
    return {
      name: '',
      description: '',
      events: ['updated'],
      conditions: { join: 'and', rows: [] },
      actions: [emptyAction()],
      fire_on_own_change: false,
      state: 'draft',
    };
  }
  return {
    name: trigger.name,
    description: trigger.description ?? '',
    events: trigger.events,
    conditions: fromTree(trigger.conditions),
    actions: trigger.actions,
    fire_on_own_change: trigger.fire_on_own_change,
    state: trigger.state,
  };
}

/** Add or change a trigger. Keeps the version it opened: a save elsewhere shows the conflict. */
function TriggerEditor({
  trigger,
  latest,
  open,
  onClose,
}: {
  trigger: TriggerOut | undefined;
  latest: TriggerOut | undefined;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const fields = useRuleFields(RECORD_TYPE, open);
  const { createTrigger, updateTrigger } = useAutomationChange();
  const [draft, setDraft] = useState<Draft>(() => draftOf(trigger));
  const [opened, setOpened] = useState<string | undefined>(trigger?.id);
  const [version, setVersion] = useState(trigger?.version);
  const [problems, setProblems] = useState<string[]>([]);
  const [conflict, setConflict] = useState<unknown>();
  if (open && opened !== (trigger?.id ?? 'new')) {
    setOpened(trigger?.id ?? 'new');
    setDraft(draftOf(trigger));
    setVersion(trigger?.version);
    setProblems([]);
  }
  const stale = latest !== undefined && version !== undefined && latest.version !== version;
  const edit = (next: Partial<Draft>) => {
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
      description: draft.description.trim() === '' ? null : draft.description,
      events: draft.events,
      conditions: toTree(draft.conditions),
      actions: draft.actions,
      fire_on_own_change: draft.fire_on_own_change,
      state: draft.state,
    };
    if (trigger === undefined) {
      createTrigger.mutate(
        { ...body, record_type: RECORD_TYPE },
        { onSuccess: done, onError: failed },
      );
    } else {
      updateTrigger.mutate(
        { id: trigger.id, version: at ?? trigger.version, body },
        { onSuccess: done, onError: failed },
      );
    }
  };
  const all = fields.data ?? [];
  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={720}
      destroyOnHidden
      title={trigger === undefined ? t('automation.triggers.add') : t('automation.triggers.edit')}
      data-testid="trigger-editor"
    >
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {stale && <Alert type="warning" showIcon message={t('organization.changed_elsewhere')} />}
        {problems.length > 0 && (
          <Alert
            type="error"
            showIcon
            data-testid="trigger-problems"
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
          <Form.Item label={t('automation.field_name')} htmlFor="trigger-name" required>
            <Input
              id="trigger-name"
              value={draft.name}
              onChange={(event) => {
                edit({ name: event.target.value });
              }}
              count={lengthLimit(200)}
              data-testid="trigger-name"
            />
          </Form.Item>
          <Form.Item label={t('automation.field_description')} htmlFor="trigger-description">
            <Input.TextArea
              id="trigger-description"
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
              options={EVENTS.map((e) => ({ value: e, label: t(`trigger_event.${e}`) }))}
              data-testid="trigger-events"
            />
          </Form.Item>
          <Form.Item
            label={t('automation.field_conditions')}
            extra={t('automation.triggers.conditions_help')}
          >
            <ConditionBuilder
              fields={all}
              value={draft.conditions}
              onChange={(conditions) => {
                edit({ conditions });
              }}
              allowOp={triggerOp}
            />
          </Form.Item>
          <Form.Item label={t('automation.field_actions')} required>
            <AfterActions
              fields={all}
              actions={draft.actions}
              onChange={(actions) => {
                edit({ actions });
              }}
              testId="trigger-action"
            />
          </Form.Item>
          <Flex gap={32} wrap>
            <Form.Item
              label={t('automation.triggers.own_change')}
              extra={t('automation.triggers.own_change.help')}
            >
              <Switch
                checked={draft.fire_on_own_change}
                onChange={(fire_on_own_change) => {
                  edit({ fire_on_own_change });
                }}
                aria-label={t('automation.triggers.own_change')}
                data-testid="trigger-own-change"
              />
            </Form.Item>
            <Form.Item label={t('automation.field_state')} extra={t('automation.field_state.help')}>
              <Select
                value={draft.state}
                onChange={(state: TriggerOut['state']) => {
                  edit({ state });
                }}
                options={(['draft', 'enabled', 'disabled'] as const).map((s) => ({
                  value: s,
                  label: t(`rule_state.${s}`),
                }))}
                style={{ minWidth: 160 }}
                aria-label={t('automation.field_state')}
                data-testid="trigger-state"
              />
            </Form.Item>
          </Flex>
        </Form>
        <Button
          type="primary"
          onClick={() => {
            save();
          }}
          loading={createTrigger.isPending || updateTrigger.isPending}
          data-testid="trigger-save"
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
