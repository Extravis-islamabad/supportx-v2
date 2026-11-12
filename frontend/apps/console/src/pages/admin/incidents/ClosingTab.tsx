import { Alert, Button, Flex, Form, InputNumber, Select, Switch, Typography } from 'antd';

import {
  useCustomFields,
  type ClosurePatch,
  type CustomFieldEntity,
  type IncidentCatalogue,
  type SettingsBase,
} from '@supportx/api-client';
import { ConflictDialog, SettingsCard, StickySaveBar, useAppearance, useLabel } from '@supportx/ui';

import { numberProblem } from '../../../numbers';
import { fieldName } from '../../customFields/values';
import { useDraft, useSettingsBase, useSettingsSave } from './helpers';
import { Problems } from './shared';

// Built-in fields a closure rule can require (REQ-INC-094); custom fields join as custom.<key>.
const BUILT_IN = [
  'resolution',
  'closure_code',
  'category_id',
  'site_id',
  'department_id',
  'group_id',
  'technician_id',
  'impact',
  'urgency',
  'level',
  'description',
  'tags',
] as const;
// Kinds of open work the checks cover (REQ-INC-095); they start working with their packages.
const OPEN_WORK_KINDS = ['tasks', 'checklists', 'child_incidents', 'approvals'] as const;
const OPEN_WORK_DEFAULTS: Record<string, string> = {
  tasks: 'warn',
  checklists: 'warn',
  child_incidents: 'warn',
  approvals: 'block',
  linked_changes: 'warn',
  child_releases: 'warn',
};

/**
 * What the Closing screen offers for one type (WP-058b S4). Incidents: everything. Releases:
 * their own fields and open-work kinds (REQ-REL-052), and no requester-reply block: a release
 * is neither auto-closed nor reopened by a reply, so that block is not shown at all.
 */
interface ClosingProfile {
  /** The type whose custom fields can be required. */
  type: CustomFieldEntity;
  builtIn: readonly string[];
  /** Conditions only the close rule may list (REQ-REL-051: a release's review completed). */
  closeConditions: readonly string[];
  openWorkKinds: readonly string[];
  /** Auto-close and the reopen window (both follow requester replies). */
  requesterReplies: boolean;
  /** Labels of this type's own wording (`settings.closing.<prefix><name>`). */
  prefix: string;
}

const PROFILES: Record<SettingsBase, ClosingProfile> = {
  incidents: {
    type: 'incident',
    builtIn: BUILT_IN,
    closeConditions: [],
    openWorkKinds: OPEN_WORK_KINDS,
    requesterReplies: true,
    prefix: '',
  },
  releases: {
    type: 'release',
    builtIn: ['resolution', 'closure_code', 'group_id', 'technician_id', 'description', 'tags'],
    closeConditions: ['review_completed'],
    openWorkKinds: ['tasks', 'approvals', 'linked_changes', 'child_releases'],
    requesterReplies: false,
    prefix: 'release.',
  },
};
const DAYS = { min: 1, max: 30 };
const AUTO_CLOSE_DEFAULT = 3; // Appendix A (D3)
// Settings whose problems show at their own field.
const PLACED = new Set([
  'resolve_requires',
  'close_requires',
  'auto_close_days',
  'reopen_window_days',
]);

/** WP-046a S3: the worklog rules' switches, in the order shown (each with its help text). */
const WORKLOG_RULES = [
  { key: 'worklogBlockClosed', code: 'worklog_block_closed' },
  { key: 'worklogCountNonworking', code: 'worklog_count_nonworking' },
  { key: 'timerAutoStart', code: 'timer_auto_start' },
] as const;

interface Draft {
  resolve: string[];
  close: string[];
  openWork: Record<string, string>;
  complete: boolean;
  taskOwners: boolean;
  /** REQ-INC-075 (WP-046a S1): an open predecessor blocks a task, or only warns. */
  waitBlocks: boolean;
  /** WP-046a S3 (REQ-INC-069/070): the worklog rules. */
  worklogBlockClosed: boolean;
  worklogCountNonworking: boolean;
  timerAutoStart: boolean;
  autoClose: boolean;
  autoCloseDays: number | null;
  reopenDays: number | null;
}

/**
 * Admin › Incidents › Closing (WP-020f): what resolving and closing need, open work, auto-close
 * and the reopen window. Auto-close never closes an incident whose requester was not told
 * (product owner, 2026-10-28): it stays off while no channel can tell requesters.
 */
export function ClosingTab({ catalogue }: { catalogue: IncidentCatalogue }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const profile = PROFILES[useSettingsBase()];
  // The type's own wording, where the text names the type.
  const own = (name: string) => t(`settings.closing.${profile.prefix}${name}`);
  const customFields = useCustomFields(profile.type);
  const { save, conflictDialog, pending, problems, byField, clear } = useSettingsSave();
  const closure = catalogue.closure;
  const source: Draft = {
    resolve: [...closure.resolve_requires],
    close: [...closure.close_requires],
    // Only the type's own kinds (lane A's #428 review): an incident never stores a release kind.
    openWork: Object.fromEntries(
      profile.openWorkKinds.map((kind) => [
        kind,
        closure.open_work[kind] ?? OPEN_WORK_DEFAULTS[kind] ?? 'warn',
      ]),
    ),
    complete: closure.complete_open_work,
    taskOwners: closure.task_owner_access,
    waitBlocks: closure.task_dependency_mode === 'block',
    worklogBlockClosed: closure.worklog_block_closed,
    worklogCountNonworking: closure.worklog_count_nonworking,
    timerAutoStart: closure.timer_auto_start,
    autoClose: closure.auto_close_days !== null,
    autoCloseDays: closure.auto_close_days ?? AUTO_CLOSE_DEFAULT,
    reopenDays: closure.reopen_window_days,
  };
  const draftState = useDraft(source, catalogue.version);
  const { draft, edit, stale } = draftState;
  const changes = (Object.keys(source) as (keyof Draft)[]).filter(
    (key) => JSON.stringify(draft[key]) !== JSON.stringify(source[key]),
  ).length;
  const reset = () => {
    clear();
    draftState.reset();
  };
  const noChannel = closure.requester_channels.length === 0;
  const blocked = closure.requester_channel_states.filter((state) => state.reason !== null);
  const fieldOptions = [
    ...profile.builtIn.map((name) => ({ value: name, label: t(`work_item.field.${name}`) })),
    ...(customFields.data ?? [])
      .filter((f) => !f.retired)
      .map((f) => ({ value: `custom.${f.key}`, label: fieldName(f, locale) })),
  ];
  const daysProblem = (value: number | null) =>
    value === null ? t('errors.field.required') : numberProblem(t, value, { ...DAYS, whole: true });
  const autoCloseProblem = draft.autoClose ? daysProblem(draft.autoCloseDays) : null;
  const reopenProblem = daysProblem(draft.reopenDays);
  const problemAt = (field: string) => {
    if (field === 'auto_close_days' && autoCloseProblem !== null) return autoCloseProblem;
    if (field === 'reopen_window_days' && reopenProblem !== null) return reopenProblem;
    return byField[field];
  };
  const submit = () => {
    if (autoCloseProblem !== null || reopenProblem !== null) return;
    const body: ClosurePatch = {
      resolve_requires: draft.resolve,
      close_requires: draft.close,
      open_work: draft.openWork,
      complete_open_work: draft.complete,
      task_owner_access: draft.taskOwners,
      task_dependency_mode: draft.waitBlocks ? 'block' : 'warn',
      worklog_block_closed: draft.worklogBlockClosed,
      worklog_count_nonworking: draft.worklogCountNonworking,
      timer_auto_start: draft.timerAutoStart,
      reopen_window_days: draft.reopenDays,
    };
    // Only sent when it changes: the server refuses switching it on without a channel.
    const autoCloseDays = draft.autoClose ? draft.autoCloseDays : null;
    if (autoCloseDays !== closure.auto_close_days) body.auto_close_days = autoCloseDays;
    save({ kind: 'closure', body }, reset, draftState.base);
  };
  const conditionOptions = profile.closeConditions.map((name) => ({
    value: name,
    label: t(`settings.closing.condition.${name}`),
  }));
  const fieldsSelect = (key: 'resolve' | 'close', field: string, testId: string) => (
    <Form.Item
      label={t(`settings.closing.${key}_requires`)}
      htmlFor={testId}
      validateStatus={problemAt(field) === undefined ? undefined : 'error'}
      help={problemAt(field) ?? own(`${key}_requires_help`)}
    >
      <Select
        id={testId}
        mode="multiple"
        value={draft[key]}
        options={key === 'close' ? [...conditionOptions, ...fieldOptions] : fieldOptions}
        optionFilterProp="label"
        style={{ width: '100%' }}
        onChange={(values: string[]) => {
          edit({ ...draft, [key]: values });
        }}
        data-testid={testId}
      />
    </Form.Item>
  );
  return (
    <Flex vertical gap={16}>
      <SettingsCard title={t('settings.closing.title')} testId="settings-closing">
        {stale && (
          <Alert
            type="warning"
            showIcon
            role="status"
            style={{ marginBottom: 12 }}
            message={t('settings.stale')}
            action={
              <Button size="small" onClick={reset} data-testid="settings-stale-reload">
                {t('live.reload')}
              </Button>
            }
            data-testid="settings-stale"
          />
        )}
        <Typography.Paragraph type="secondary">{own('help')}</Typography.Paragraph>
        <Form layout="vertical" component="div">
          {fieldsSelect('resolve', 'resolve_requires', 'settings-resolve-requires')}
          {fieldsSelect('close', 'close_requires', 'settings-close-requires')}
          <fieldset style={{ border: 0, padding: 0, margin: '0 0 16px' }}>
            <legend>
              <Typography.Text strong>{t('settings.closing.open_work')}</Typography.Text>
            </legend>
            <Typography.Paragraph type="secondary" data-testid="settings-open-work-note">
              {own('open_work_help')}
            </Typography.Paragraph>
            <Flex gap={16} wrap>
              {profile.openWorkKinds.map((kind) => (
                <Form.Item
                  key={kind}
                  label={t(`open_work_kind.${kind}`)}
                  htmlFor={`settings-open-work-${kind}`}
                >
                  <Select
                    id={`settings-open-work-${kind}`}
                    value={draft.openWork[kind]}
                    style={{ width: 200 }}
                    onChange={(mode: string) => {
                      edit({ ...draft, openWork: { ...draft.openWork, [kind]: mode } });
                    }}
                    options={['warn', 'block'].map((mode) => ({
                      value: mode,
                      label: t(`open_work_mode.${mode}`),
                    }))}
                    data-testid={`settings-open-work-${kind}`}
                  />
                </Form.Item>
              ))}
            </Flex>
            <Flex gap={12} align="start">
              <Switch
                id="settings-complete-open-work"
                checked={draft.complete}
                onChange={(checked) => {
                  edit({ ...draft, complete: checked });
                }}
                data-testid="settings-complete-open-work"
              />
              <label htmlFor="settings-complete-open-work">
                <Typography.Text strong>{t('settings.closing.complete_open_work')}</Typography.Text>
                <br />
                <Typography.Text type="secondary">{own('complete_open_work_help')}</Typography.Text>
              </label>
            </Flex>
            <Flex gap={12} align="start">
              <Switch
                id="settings-task-owner-access"
                checked={draft.taskOwners}
                onChange={(checked) => {
                  edit({ ...draft, taskOwners: checked });
                }}
                data-testid="settings-task-owner-access"
              />
              <label htmlFor="settings-task-owner-access">
                <Typography.Text strong>{own('task_owner_access')}</Typography.Text>
                <br />
                <Typography.Text type="secondary">{own('task_owner_access_help')}</Typography.Text>
              </label>
            </Flex>
            <Flex gap={12} align="start">
              <Switch
                id="settings-task-dependency-mode"
                checked={draft.waitBlocks}
                onChange={(checked) => {
                  edit({ ...draft, waitBlocks: checked });
                }}
                data-testid="settings-task-dependency-mode"
              />
              <label htmlFor="settings-task-dependency-mode">
                <Typography.Text strong>
                  {t('settings.closing.task_dependency_mode')}
                </Typography.Text>
                <br />
                <Typography.Text type="secondary">
                  {t('settings.closing.task_dependency_mode_help')}
                </Typography.Text>
              </label>
            </Flex>
            {WORKLOG_RULES.map(({ key, code }) => (
              <Flex key={key} gap={12} align="start">
                <Switch
                  id={`settings-${code}`}
                  checked={draft[key]}
                  onChange={(checked) => {
                    edit({ ...draft, [key]: checked });
                  }}
                  data-testid={`settings-${code}`}
                />
                <label htmlFor={`settings-${code}`}>
                  {/* The type's own wording (releases say "release"), lane C's profile. */}
                  <Typography.Text strong>{own(code)}</Typography.Text>
                  <br />
                  <Typography.Text type="secondary">{own(`${code}_help`)}</Typography.Text>
                </label>
              </Flex>
            ))}
          </fieldset>
          {/* Releases have no requester replies: no auto-close, no reopen window. */}
          {profile.requesterReplies && (
            <>
              <Flex gap={12} align="start" style={{ marginBottom: 8 }}>
                <Switch
                  id="settings-auto-close"
                  checked={draft.autoClose}
                  // Never auto-close what the requester was never told (product owner, 2026-10-28).
                  disabled={noChannel && !draft.autoClose}
                  onChange={(checked) => {
                    edit({ ...draft, autoClose: checked });
                  }}
                  data-testid="settings-auto-close"
                />
                <label htmlFor="settings-auto-close">
                  <Typography.Text strong>{t('settings.closing.auto_close')}</Typography.Text>
                  <br />
                  <Typography.Text type="secondary">
                    {t('settings.closing.auto_close_help')}
                  </Typography.Text>
                </label>
              </Flex>
              {noChannel && (
                <Alert
                  type="info"
                  showIcon
                  role="note"
                  style={{ marginBottom: 12 }}
                  message={t('settings.closing.auto_close_needs_notifications')}
                  // Why each channel cannot tell requesters yet, so the admin knows what to fix (QA BUG-02).
                  description={
                    blocked.length > 0 && (
                      <ul
                        style={{ margin: 0, paddingInlineStart: 20 }}
                        data-testid="settings-requester-channels"
                      >
                        {blocked.map((state) => (
                          <li key={state.channel}>
                            {t('settings.closing.channel_state', {
                              channel: t(`notification_channel.${state.channel}`),
                              reason: t(`requester_channel_reason.${state.reason ?? ''}`),
                            })}
                          </li>
                        ))}
                      </ul>
                    )
                  }
                  data-testid="settings-auto-close-needs"
                />
              )}
              <Flex gap={16} wrap>
                <Form.Item
                  label={t('settings.closing.auto_close_days')}
                  htmlFor="settings-auto-close-days"
                  validateStatus={problemAt('auto_close_days') === undefined ? undefined : 'error'}
                  help={problemAt('auto_close_days') ?? t('settings.closing.days_range', DAYS)}
                >
                  <InputNumber
                    id="settings-auto-close-days"
                    value={draft.autoCloseDays}
                    disabled={!draft.autoClose}
                    style={{ width: 160 }}
                    onChange={(value) => {
                      edit({ ...draft, autoCloseDays: typeof value === 'number' ? value : null });
                    }}
                    data-testid="settings-auto-close-days"
                  />
                </Form.Item>
                <Form.Item
                  label={t('settings.closing.reopen_window_days')}
                  htmlFor="settings-reopen-days"
                  validateStatus={
                    problemAt('reopen_window_days') === undefined ? undefined : 'error'
                  }
                  help={problemAt('reopen_window_days') ?? t('settings.closing.reopen_window_help')}
                >
                  <InputNumber
                    id="settings-reopen-days"
                    value={draft.reopenDays}
                    style={{ width: 160 }}
                    onChange={(value) => {
                      edit({ ...draft, reopenDays: typeof value === 'number' ? value : null });
                    }}
                    data-testid="settings-reopen-days"
                  />
                </Form.Item>
              </Flex>
            </>
          )}
          {/* A refusal with no field to point at (QA WP-029 BUG-02); field ones show in place. */}
          {(Object.keys(byField).length === 0 ||
            Object.keys(byField).some((key) => !PLACED.has(key))) && (
            <Problems problems={problems} />
          )}
        </Form>
      </SettingsCard>
      {/* One save bar for the page (template E, D-147), below the card as on every page. */}
      <StickySaveBar
        changes={changes}
        saving={pending}
        onDiscard={reset}
        onSave={submit}
        testId="settings-closing-save-bar"
      />
      <ConflictDialog {...conflictDialog} />
    </Flex>
  );
}
