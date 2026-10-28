import {
  Alert,
  Button,
  Card,
  Flex,
  Form,
  InputNumber,
  Select,
  Space,
  Switch,
  Typography,
} from 'antd';

import { useCustomFields, type ClosurePatch, type IncidentCatalogue } from '@supportx/api-client';
import { ConflictDialog, useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { numberProblem } from '../../../numbers';
import { fieldName } from '../../customFields/values';
import { useDraft, useSettingsSave } from './helpers';
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

interface Draft {
  resolve: string[];
  close: string[];
  openWork: Record<string, string>;
  complete: boolean;
  taskOwners: boolean;
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
  const customFields = useCustomFields('incident');
  const { save, conflictDialog, pending, problems, byField, clear } = useSettingsSave();
  const closure = catalogue.closure;
  const source: Draft = {
    resolve: [...closure.resolve_requires],
    close: [...closure.close_requires],
    openWork: { ...OPEN_WORK_DEFAULTS, ...closure.open_work },
    complete: closure.complete_open_work,
    taskOwners: closure.task_owner_access,
    autoClose: closure.auto_close_days !== null,
    autoCloseDays: closure.auto_close_days ?? AUTO_CLOSE_DEFAULT,
    reopenDays: closure.reopen_window_days,
  };
  const draftState = useDraft(source, catalogue.version);
  const { draft, edit, stale, dirty } = draftState;
  const reset = () => {
    clear();
    draftState.reset();
  };
  const noChannel = closure.requester_channels.length === 0;
  const fieldOptions = [
    ...BUILT_IN.map((name) => ({ value: name, label: t(`work_item.field.${name}`) })),
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
      reopen_window_days: draft.reopenDays,
    };
    // Only sent when it changes: the server refuses switching it on without a channel.
    const autoCloseDays = draft.autoClose ? draft.autoCloseDays : null;
    if (autoCloseDays !== closure.auto_close_days) body.auto_close_days = autoCloseDays;
    save({ kind: 'closure', body }, reset, draftState.base);
  };
  const fieldsSelect = (key: 'resolve' | 'close', field: string, testId: string) => (
    <Form.Item
      label={t(`settings.closing.${key}_requires`)}
      htmlFor={testId}
      validateStatus={problemAt(field) === undefined ? undefined : 'error'}
      help={problemAt(field) ?? t(`settings.closing.${key}_requires_help`)}
    >
      <Select
        id={testId}
        mode="multiple"
        value={draft[key]}
        options={fieldOptions}
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
    <Card title={t('settings.closing.title')} data-testid="settings-closing">
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
      <Typography.Paragraph type="secondary">{t('settings.closing.help')}</Typography.Paragraph>
      <Form layout="vertical" component="div">
        {fieldsSelect('resolve', 'resolve_requires', 'settings-resolve-requires')}
        {fieldsSelect('close', 'close_requires', 'settings-close-requires')}
        <fieldset style={{ border: 0, padding: 0, margin: '0 0 16px' }}>
          <legend>
            <Typography.Text strong>{t('settings.closing.open_work')}</Typography.Text>
          </legend>
          <Typography.Paragraph type="secondary" data-testid="settings-open-work-note">
            {t('settings.closing.open_work_help')}
          </Typography.Paragraph>
          <Flex gap={16} wrap>
            {OPEN_WORK_KINDS.map((kind) => (
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
              <Typography.Text type="secondary">
                {t('settings.closing.complete_open_work_help')}
              </Typography.Text>
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
              <Typography.Text strong>{t('settings.closing.task_owner_access')}</Typography.Text>
              <br />
              <Typography.Text type="secondary">
                {t('settings.closing.task_owner_access_help')}
              </Typography.Text>
            </label>
          </Flex>
        </fieldset>
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
            validateStatus={problemAt('reopen_window_days') === undefined ? undefined : 'error'}
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
        {/* A refusal with no field to point at (QA WP-029 BUG-02); field ones show in place. */}
        {(Object.keys(byField).length === 0 ||
          Object.keys(byField).some((key) => !PLACED.has(key))) && <Problems problems={problems} />}
        <Space>
          <WriteButton
            type="primary"
            loading={pending}
            disabled={!dirty}
            onClick={submit}
            data-testid="settings-closing-save"
          >
            {t('actions.save')}
          </WriteButton>
          <Button disabled={!dirty} onClick={reset}>
            {t('actions.reset')}
          </Button>
        </Space>
      </Form>
      <ConflictDialog {...conflictDialog} />
    </Card>
  );
}
