import { LockOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
} from 'antd';
import { useState } from 'react';

import {
  ApiError,
  problemKeys,
  useRepeatRuleChange,
  useRepeatRules,
  useUnits,
  type RepeatRule,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  EmptyText,
  lengthLimit,
  markHandled,
  reportError,
  useLabel,
  WriteButton,
} from '@supportx/ui';

const DEFAULT_NAME = 'Same category and site'; // the server's seeded name (labelled)
const MATCHES = ['category_site', 'category'] as const;
type Match = (typeof MATCHES)[number];

interface Draft {
  name: string;
  match: Match;
  threshold: number;
  window_hours: number;
  notify_group_id: string | null;
}

const BLANK: Draft = {
  name: '',
  match: 'category_site',
  threshold: 10,
  window_hours: 24,
  notify_group_id: null,
};

/** The default rule's name in the user's language while it keeps its seeded name. */
function ruleName(t: ReturnType<typeof useLabel>, rule: RepeatRule): string {
  return rule.is_default && rule.name === DEFAULT_NAME ? t('repeat_rule.default') : rule.name;
}

/**
 * Admin › Incidents › Repeated incidents (WP-044c D16, REQ-PRB-068): rules that tell a group
 * when N or more incidents in the same category (and site) arrive within H hours, without AI.
 * The problem module's (D-140 item 5): without it, licence managers see the section locked with
 * the upgrade hint, as locked sections are everywhere; nobody else sees it. Live: a rule an
 * admin changes elsewhere shows at once.
 */
export function RepeatRulesTab({ entitled }: { entitled: boolean }) {
  const t = useLabel();
  if (!entitled) {
    return (
      <Card title={t('settings.section.repeat-rules')} data-testid="settings-repeat-rules">
        <Alert
          type="info"
          showIcon
          icon={<LockOutlined />}
          message={t('licence.locked')}
          description={t('licence.upgrade_hint')}
          data-testid="repeat-rules-locked"
        />
      </Card>
    );
  }
  return <Rules />;
}

function Rules() {
  const t = useLabel();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const rules = useRepeatRules();
  const groups = useUnits('groups');
  const change = useRepeatRuleChange();
  // `shown`: the name as the form opened (the default's, translated): unchanged, it is not sent.
  const [editing, setEditing] = useState<{
    rule: RepeatRule | null;
    draft: Draft;
    shown: string;
  } | null>(null);
  const [problems, setProblems] = useState<Record<string, string>>({});
  useTenantChannel((event) => {
    if (event.type === 'work_items.problem_repeats_changed') {
      void queryClient.invalidateQueries({ queryKey: problemKeys.repeatRules });
    }
  });
  const groupName = (id: string | null) =>
    id === null
      ? t('repeat_rules.their_group')
      : (groups.data?.find((g) => g.id === id)?.name ?? '');
  const failed = (error: unknown) => {
    if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
      markHandled(error);
      setProblems(
        Object.fromEntries(
          error.fieldErrors.map((f) => [
            f.field.replace(/^body\./, ''),
            t(f.message_key, f.params ?? {}),
          ]),
        ),
      );
      return;
    }
    reportError(error);
  };
  const save = () => {
    if (editing === null) return;
    const { rule, draft, shown } = editing;
    if (draft.name.trim() === '') {
      setProblems({ name: t('errors.field.required') });
      return;
    }
    setProblems({});
    const done = {
      onSuccess: () => {
        void message.success(t('common.saved'));
        setEditing(null);
      },
      onError: failed,
    };
    if (rule === null) {
      change.mutate(
        { kind: 'create', body: { ...draft, enabled: true }, key: crypto.randomUUID() },
        done,
      );
    } else {
      const { name, ...rest } = draft;
      const body = name === shown ? rest : draft;
      change.mutate({ kind: 'update', id: rule.id, version: rule.version, body }, done);
    }
  };
  const help = (field: string) =>
    problems[field] === undefined
      ? {}
      : { validateStatus: 'error' as const, help: problems[field] };
  const set = (next: Partial<Draft>) => {
    setEditing((was) => (was === null ? was : { ...was, draft: { ...was.draft, ...next } }));
  };
  return (
    <Card
      title={t('settings.section.repeat-rules')}
      extra={
        <WriteButton
          type="primary"
          onClick={() => {
            setProblems({});
            setEditing({ rule: null, draft: BLANK, shown: '' });
          }}
          data-testid="repeat-rule-add"
        >
          {t('repeat_rules.add')}
        </WriteButton>
      }
      data-testid="settings-repeat-rules"
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        <Alert type="info" showIcon message={t('repeat_rules.help')} />
        <Table<RepeatRule>
          rowKey="id"
          loading={rules.isLoading}
          dataSource={rules.data ?? []}
          pagination={false}
          locale={{ emptyText: <EmptyText>{t('repeat_rules.empty')}</EmptyText> }}
          data-testid="repeat-rules"
          columns={[
            {
              key: 'name',
              title: t('repeat_rules.name'),
              render: (_, rule) => <bdi dir="auto">{ruleName(t, rule)}</bdi>,
            },
            {
              key: 'when',
              title: t('repeat_rules.when'),
              render: (_, rule) =>
                t('repeat_rules.summary', {
                  count: rule.threshold,
                  match: t(`repeat_match.${rule.match}`),
                  hours: rule.window_hours,
                }),
            },
            {
              key: 'group',
              title: t('repeat_rules.notify'),
              render: (_, rule) => <bdi>{groupName(rule.notify_group_id)}</bdi>,
            },
            {
              key: 'enabled',
              title: t('repeat_rules.enabled'),
              render: (_, rule) => (
                <Switch
                  checked={rule.enabled}
                  aria-label={t('repeat_rules.enabled')}
                  onChange={(enabled) => {
                    change.mutate(
                      { kind: 'update', id: rule.id, version: rule.version, body: { enabled } },
                      { onError: reportError },
                    );
                  }}
                  data-testid={`repeat-rule-enabled-${rule.id}`}
                />
              ),
            },
            {
              key: 'actions',
              title: <span className="sx-visually-hidden">{t('repeat_rules.actions')}</span>,
              render: (_, rule) => (
                <Space>
                  <Button
                    type="link"
                    onClick={() => {
                      setProblems({});
                      setEditing({
                        rule,
                        draft: {
                          name: ruleName(t, rule),
                          match: rule.match,
                          threshold: rule.threshold,
                          window_hours: rule.window_hours,
                          notify_group_id: rule.notify_group_id,
                        },
                        shown: ruleName(t, rule),
                      });
                    }}
                    data-testid={`repeat-rule-edit-${rule.id}`}
                  >
                    {t('actions.edit')}
                  </Button>
                  {!rule.is_default && (
                    <Popconfirm
                      title={t('repeat_rules.remove_confirm')}
                      okText={t('repeat_rules.remove')}
                      cancelText={t('actions.cancel')}
                      onConfirm={() => {
                        change.mutate(
                          { kind: 'delete', id: rule.id, version: rule.version },
                          { onError: reportError },
                        );
                      }}
                    >
                      <Button type="link" danger data-testid={`repeat-rule-remove-${rule.id}`}>
                        {t('repeat_rules.remove')}
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Space>
      <Modal
        open={editing !== null}
        title={t(editing?.rule == null ? 'repeat_rules.add' : 'repeat_rules.edit')}
        okText={t('actions.save')}
        cancelText={t('actions.cancel')}
        confirmLoading={change.isPending}
        onOk={save}
        onCancel={() => {
          setEditing(null);
        }}
        destroyOnHidden
        data-testid="repeat-rule-editor"
      >
        {editing !== null && (
          <Form layout="vertical" component="div">
            <Form.Item
              label={t('repeat_rules.name')}
              htmlFor="repeat-name"
              required
              {...help('name')}
            >
              <Input
                id="repeat-name"
                dir="auto"
                count={lengthLimit(200)}
                value={editing.draft.name}
                onChange={(e) => {
                  set({ name: e.target.value });
                }}
                data-testid="repeat-rule-name"
              />
            </Form.Item>
            <Form.Item label={t('repeat_rules.match')} htmlFor="repeat-match" {...help('match')}>
              <Select
                id="repeat-match"
                value={editing.draft.match}
                onChange={(match: Match) => {
                  set({ match });
                }}
                options={MATCHES.map((m) => ({ value: m, label: t(`repeat_match.${m}`) }))}
                data-testid="repeat-rule-match"
              />
            </Form.Item>
            <Space wrap>
              <Form.Item
                label={t('repeat_rules.threshold')}
                htmlFor="repeat-threshold"
                {...help('threshold')}
              >
                <InputNumber
                  id="repeat-threshold"
                  min={2}
                  max={1000}
                  value={editing.draft.threshold}
                  onChange={(n) => {
                    set({ threshold: n ?? 2 });
                  }}
                  data-testid="repeat-rule-threshold"
                />
              </Form.Item>
              <Form.Item
                label={t('repeat_rules.window')}
                htmlFor="repeat-window"
                {...help('window_hours')}
              >
                <InputNumber
                  id="repeat-window"
                  min={1}
                  max={2160}
                  value={editing.draft.window_hours}
                  onChange={(n) => {
                    set({ window_hours: n ?? 1 });
                  }}
                  data-testid="repeat-rule-window"
                />
              </Form.Item>
            </Space>
            <Form.Item
              label={t('repeat_rules.notify')}
              htmlFor="repeat-group"
              help={problems.notify_group_id ?? t('repeat_rules.notify_help')}
              validateStatus={problems.notify_group_id === undefined ? undefined : 'error'}
            >
              <Select
                id="repeat-group"
                allowClear
                placeholder={t('repeat_rules.their_group')}
                value={editing.draft.notify_group_id ?? undefined}
                onChange={(id: string | undefined) => {
                  set({ notify_group_id: id ?? null });
                }}
                options={(groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))}
                data-testid="repeat-rule-group"
              />
            </Form.Item>
          </Form>
        )}
      </Modal>
    </Card>
  );
}
