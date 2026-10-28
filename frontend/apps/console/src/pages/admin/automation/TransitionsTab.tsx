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
  Table,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useAutomationChange,
  useRoles,
  useRuleFields,
  useStructure,
  useTransitionSettings,
  type TransitionOut,
  type TriggerActionIO,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import {
  ConflictDialog,
  FormProblem,
  lengthLimit,
  markHandled,
  useAccess,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

import { roleName } from '../roleName';

import { AfterActions } from './AfterActions';
import { ConditionBuilder } from './fields';
import { fromTree, stateOp, toTree, type Conditions } from './rules';
import { conditionAt, isAt, useEditorProblems, whereOf } from './problems';
import { ProblemList } from './ProblemList';

const RECORD_TYPE = 'incident';
// The person-run life-cycle actions, in the record page's order (REQ-INC-046).
const ACTIONS = [
  'start_work',
  'wait_requester',
  'wait_third_party',
  'resume',
  'resolve',
  'close',
  'reopen',
  'cancel',
  'undo_cancel',
] as const;
const RELATIVES = [
  'requester',
  'assignee',
  'group_head',
  'requester_manager',
  'department_head',
] as const;
const LANGUAGES = ['en', 'ar', 'ur'] as const;
const CONFIRMATION_MAX = 500;

interface Row {
  action: string;
  setting: TransitionOut | undefined;
}

/**
 * Admin › Incidents › Transitions (WP-029 part 2; REQ-WF-003, 004): who may run each status
 * action, when it is offered, a confirmation and what runs after it. An action without settings
 * is offered to everyone with its permission, as before.
 */
export function TransitionsTab() {
  const t = useLabel();
  const listFormat = useListFormat();
  const { can } = useAccess();
  const settings = useTransitionSettings(RECORD_TYPE, can('automation.view'));
  const [editing, setEditing] = useState<string>();
  const byAction = new Map((settings.data ?? []).map((s) => [s.action, s]));
  const rows: Row[] = ACTIONS.map((action) => ({ action, setting: byAction.get(action) }));
  const summary = (setting: TransitionOut | undefined) => {
    if (setting === undefined) return t('automation.transitions.anyone');
    const parts = [
      setting.roles.length + setting.group_ids.length + setting.relatives.length > 0
        ? t('automation.transitions.limited')
        : t('automation.transitions.anyone'),
    ];
    if (setting.conditions !== null) parts.push(t('automation.transitions.has_conditions'));
    if (setting.confirmation !== null) parts.push(t('automation.transitions.has_confirmation'));
    if (setting.after_actions.length > 0) {
      parts.push(t('automation.transitions.has_after', { count: setting.after_actions.length }));
    }
    return listFormat(parts);
  };
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Typography.Paragraph type="secondary" style={{ margin: 0, maxWidth: 720 }}>
        {t('automation.transitions.explain')}
      </Typography.Paragraph>
      <Table<Row>
        rowKey="action"
        loading={settings.isPending}
        dataSource={rows}
        pagination={false}
        data-testid="transitions-table"
        columns={[
          {
            key: 'action',
            title: t('automation.transitions.col.action'),
            render: (_, row) => t(`work_item_action.${row.action}`),
          },
          {
            key: 'summary',
            title: t('automation.transitions.col.settings'),
            render: (_, row) => (
              <span data-testid={`transition-summary-${row.action}`}>{summary(row.setting)}</span>
            ),
          },
          ...(can('automation.manage')
            ? [
                {
                  key: 'edit',
                  title: <span className="sr-only">{t('automation.col.actions')}</span>,
                  render: (_: unknown, row: Row) => (
                    <Button
                      size="small"
                      onClick={() => {
                        setEditing(row.action);
                      }}
                      data-testid={`transition-edit-${row.action}`}
                    >
                      {t('actions.edit')}
                    </Button>
                  ),
                },
              ]
            : []),
        ]}
      />
      <TransitionEditor
        action={editing}
        setting={editing === undefined ? undefined : byAction.get(editing)}
        onClose={() => {
          setEditing(undefined);
        }}
      />
    </Space>
  );
}

interface Draft {
  roles: string[];
  group_ids: string[];
  relatives: TransitionOut['relatives'];
  conditions: Conditions;
  confirmation: Record<string, string>;
  after_actions: TriggerActionIO[];
}

function draftOf(setting: TransitionOut | undefined): Draft {
  return {
    roles: setting?.roles ?? [],
    group_ids: setting?.group_ids ?? [],
    relatives: setting?.relatives ?? [],
    conditions: fromTree(setting?.conditions),
    confirmation: { ...(setting?.confirmation ?? {}) },
    after_actions: setting?.after_actions ?? [],
  };
}

function TransitionEditor({
  action,
  setting,
  onClose,
}: {
  action: string | undefined;
  setting: TransitionOut | undefined;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const open = action !== undefined;
  const fields = useRuleFields(RECORD_TYPE, open);
  const roles = useRoles(open);
  const groups = useStructure('groups', open);
  const { saveTransition, resetTransition } = useAutomationChange();
  const [draft, setDraft] = useState<Draft>(() => draftOf(setting));
  const [opened, setOpened] = useState<string | undefined>(action);
  const [version, setVersion] = useState(setting?.version ?? 0);
  // The settings as opened: the conflict dialog compares them with the live ones (BUG-05).
  const [base, setBase] = useState(setting);
  const issues = useEditorProblems();
  const { problems } = issues;
  // A refusal with no problem list (a rule, a limit) is shown here (QA WP-029 BUG-02).
  const problem = useFormProblem();
  const [conflict, setConflict] = useState<unknown>();
  if (open && opened !== action) {
    setOpened(action);
    setDraft(draftOf(setting));
    setVersion(setting?.version ?? 0);
    setBase(setting);
    issues.clear();
    problem.clear();
  }
  const stale = (setting?.version ?? 0) !== version;
  const edit = (next: Partial<Draft>) => {
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
    if (action === undefined) return;
    const confirmation = Object.fromEntries(
      Object.entries(draft.confirmation).filter(([, text]) => text.trim() !== ''),
    );
    saveTransition.mutate(
      {
        recordType: RECORD_TYPE,
        action,
        version: at,
        body: {
          roles: draft.roles,
          group_ids: draft.group_ids,
          relatives: draft.relatives,
          conditions: toTree(draft.conditions),
          confirmation: Object.keys(confirmation).length > 0 ? confirmation : null,
          after_actions: draft.after_actions,
        },
      },
      {
        onSuccess: () => {
          void message.success(t('common.saved'));
          onClose();
        },
        onError: failed,
      },
    );
  };
  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={720}
      destroyOnHidden
      title={
        action === undefined
          ? undefined
          : t('automation.transitions.edit', { action: t(`work_item_action.${action}`) })
      }
      data-testid="transition-editor"
    >
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {stale && <Alert type="warning" showIcon message={t('organization.changed_elsewhere')} />}
        <FormProblem problem={problem} />
        <ProblemList problems={problems} testId="transition-problems" />
        <Form layout="vertical">
          <Typography.Title level={5}>{t('automation.transitions.who')}</Typography.Title>
          <Typography.Paragraph type="secondary">
            {t('automation.transitions.who_help')}
          </Typography.Paragraph>
          <Form.Item
            label={t('automation.transitions.roles')}
            validateStatus={issues.status('roles')}
          >
            <Select
              mode="multiple"
              value={draft.roles}
              onChange={(next: string[]) => {
                edit({ roles: next });
              }}
              options={(roles.data ?? []).map((role) => ({
                value: role.key,
                label: roleName(role, t),
              }))}
              optionFilterProp="label"
              aria-label={t('automation.transitions.roles')}
              data-testid="transition-roles"
            />
          </Form.Item>
          <Form.Item
            label={t('automation.transitions.groups')}
            validateStatus={issues.status('group_ids')}
          >
            <Select
              mode="multiple"
              value={draft.group_ids}
              onChange={(next: string[]) => {
                edit({ group_ids: next });
              }}
              options={(groups.data ?? [])
                .filter((g) => !g.disabled || draft.group_ids.includes(g.id))
                .map((g) => ({ value: g.id, label: g.name }))}
              optionFilterProp="label"
              aria-label={t('automation.transitions.groups')}
              data-testid="transition-groups"
            />
          </Form.Item>
          <Form.Item
            label={t('automation.transitions.relatives')}
            validateStatus={issues.status('relatives')}
          >
            <Checkbox.Group
              value={draft.relatives}
              onChange={(next) => {
                edit({ relatives: next });
              }}
              options={RELATIVES.map((r) => ({ value: r, label: t(`transition_relative.${r}`) }))}
              data-testid="transition-relatives"
            />
          </Form.Item>
          <Form.Item
            label={t('automation.transitions.when')}
            validateStatus={issues.status('conditions')}
            extra={t('automation.transitions.when_help')}
          >
            <ConditionBuilder
              invalid={(index) => conditionAt(problems, index)}
              fields={fields.data ?? []}
              value={draft.conditions}
              onChange={(conditions) => {
                edit({ conditions });
              }}
              allowOp={stateOp}
            />
          </Form.Item>
          <Form.Item
            label={t('automation.transitions.confirmation')}
            validateStatus={issues.status('confirmation')}
            extra={t('automation.transitions.confirmation_help')}
          >
            <Space direction="vertical" style={{ width: '100%' }}>
              {LANGUAGES.map((language) => (
                <Input
                  key={language}
                  dir={language === 'en' ? 'ltr' : 'rtl'}
                  prefix={
                    <Typography.Text type="secondary">{t(`locale.${language}`)}</Typography.Text>
                  }
                  value={draft.confirmation[language] ?? ''}
                  onChange={(event) => {
                    edit({
                      confirmation: { ...draft.confirmation, [language]: event.target.value },
                    });
                  }}
                  count={lengthLimit(CONFIRMATION_MAX)}
                  aria-label={t('automation.transitions.confirmation_in', {
                    language: t(`locale.${language}`),
                  })}
                  data-testid={`transition-confirmation-${language}`}
                />
              ))}
            </Space>
          </Form.Item>
          <Form.Item
            label={t('automation.transitions.after')}
            validateStatus={issues.status('after_actions')}
            extra={t('automation.transitions.after_help')}
          >
            <AfterActions
              invalid={(index) => isAt(problems, `after_actions.${String(index)}`)}
              fields={fields.data ?? []}
              actions={draft.after_actions}
              onChange={(after_actions) => {
                edit({ after_actions });
              }}
              testId="transition-after"
            />
          </Form.Item>
        </Form>
        <Flex gap={8} wrap>
          <Button
            type="primary"
            onClick={() => {
              save();
            }}
            loading={saveTransition.isPending}
            data-testid="transition-save"
          >
            {t('actions.save')}
          </Button>
          {setting !== undefined && action !== undefined && (
            <Popconfirm
              title={t('automation.transitions.reset_confirm')}
              okText={t('automation.transitions.reset')}
              cancelText={t('actions.cancel')}
              onConfirm={() => {
                resetTransition.mutate(
                  { recordType: RECORD_TYPE, action, version: setting.version },
                  {
                    onSuccess: () => {
                      void message.success(t('common.saved'));
                      onClose();
                    },
                    onError: failed,
                  },
                );
              }}
            >
              <Button danger data-testid="transition-reset">
                {t('automation.transitions.reset')}
              </Button>
            </Popconfirm>
          )}
        </Flex>
      </Space>
      <ConflictDialog
        open={conflict !== undefined}
        error={conflict}
        fieldLabel={(field) => whereOf(t, field)}
        opened={base}
        latest={setting}
        onReload={() => {
          setConflict(undefined);
          onClose();
        }}
        onKeepMine={() => {
          setConflict(undefined);
          const latest = setting?.version ?? 0;
          setVersion(latest);
          setBase(setting);
          save(latest);
        }}
      />
    </Drawer>
  );
}
