import {
  Alert,
  Button,
  Checkbox,
  Flex,
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
  Typography,
} from 'antd';

import type { IncidentCatalogue } from '@supportx/api-client';
import {
  ConflictDialog,
  SettingsCard,
  StickySaveBar,
  useAppearance,
  useLabel,
  lengthLimit,
} from '@supportx/ui';

import { scaleLabel } from '../../incidents/labels';
import { useDraft, useSettingsBase, useSettingsSave } from './helpers';
import { numberProblem } from '../../../numbers';
import { Problems } from './shared';

const IMPACTS = ['one_person', 'team', 'department_or_site', 'organisation'] as const;
const URGENCIES = ['low', 'medium', 'high', 'critical'] as const;
const PRIORITIES = ['p1', 'p2', 'p3', 'p4'] as const;
const FIRST_RESPONSE = ['reply', 'public_note', 'private_note'] as const;
// What a mail may set (WP-046a S6; REQ-INC-025), in the server's order.
const MAIL_FIELDS = ['category', 'priority', 'group', 'technician', 'template'] as const;
const NONE = '';

function StaleNotice({ onReload }: { onReload: () => void }) {
  const t = useLabel();
  return (
    <Alert
      type="warning"
      showIcon
      role="status"
      style={{ marginBottom: 12 }}
      message={t('settings.stale')}
      action={
        <Button size="small" onClick={onReload} data-testid="settings-stale-reload">
          {t('live.reload')}
        </Button>
      }
      data-testid="settings-stale"
    />
  );
}

/** The tab's settings as one draft (D-147 template E): every card edits it, one bar saves it. */
interface General {
  prefix: string;
  next: number | null;
  impact: string;
  urgency: string;
  priority: IncidentCatalogue['default_priority'];
  auto: boolean;
  follow: boolean;
  dueTime: boolean;
  first: string[];
  mailCommands: boolean;
  mailFields: string[];
  ccFromMail: boolean;
}

function savedOf(catalogue: IncidentCatalogue): General {
  return {
    prefix: catalogue.prefix,
    next: catalogue.next_number,
    impact: catalogue.default_impact ?? NONE,
    urgency: catalogue.default_urgency ?? NONE,
    priority: catalogue.default_priority,
    auto: catalogue.auto_status_on_assign,
    follow: catalogue.keep_following_on_handover,
    dueTime: catalogue.portal_show_due_time,
    first: [...catalogue.first_response_on],
    mailCommands: catalogue.mail_commands,
    mailFields: [...(catalogue.mail_command_fields ?? [])],
    ccFromMail: catalogue.cc_from_first_mail,
  };
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/**
 * Numbering, the create form's defaults and the automatic moves (template E, D-147): grouped
 * cards with no buttons of their own, and one save bar that sends only what changed, with
 * If-Match on the version the draft started from (QA WP-026 BUG-01), all or nothing (BUG-01).
 */
export function GeneralTab({ catalogue }: { catalogue: IncidentCatalogue }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { save, conflictDialog, pending, problems, byField, clear } = useSettingsSave();
  // Mailboxes make incidents: the mail settings are theirs only.
  const incidents = useSettingsBase() === 'incidents';
  const saved = savedOf(catalogue);
  const state = useDraft(saved, catalogue.version);
  const { draft, stale, base } = state;
  const set = (patch: Partial<General>) => {
    state.edit({ ...draft, ...patch });
  };
  const changedKeys = (Object.keys(saved) as (keyof General)[]).filter(
    (key) => !same(draft[key], saved[key]),
  );
  const discard = () => {
    clear();
    state.reset();
  };
  // A number that is not whole, or below 1, is refused here, never rounded (QA WP-026 BUG-03).
  const nextProblem =
    draft.next === null
      ? t('errors.field.required')
      : numberProblem(t, draft.next, { min: 1, whole: true });
  const submit = () => {
    if (nextProblem !== null || draft.next === null) return;
    const prefix = draft.prefix.trim().toUpperCase();
    const body: Record<string, unknown> = {};
    if (prefix !== catalogue.prefix) body.prefix = prefix;
    if (draft.next !== catalogue.next_number) body.next_number = draft.next;
    if (draft.impact !== saved.impact)
      body.default_impact = draft.impact === NONE ? null : draft.impact;
    if (draft.urgency !== saved.urgency)
      body.default_urgency = draft.urgency === NONE ? null : draft.urgency;
    if (draft.priority !== saved.priority) body.default_priority = draft.priority;
    if (draft.auto !== saved.auto) body.auto_status_on_assign = draft.auto;
    if (draft.follow !== saved.follow) body.keep_following_on_handover = draft.follow;
    if (draft.dueTime !== saved.dueTime) body.portal_show_due_time = draft.dueTime;
    if (!same(draft.first, saved.first)) body.first_response_on = draft.first;
    if (incidents) {
      if (draft.mailCommands !== saved.mailCommands) body.mail_commands = draft.mailCommands;
      if (!same(draft.mailFields, saved.mailFields)) {
        body.mail_command_fields = MAIL_FIELDS.filter((f) => draft.mailFields.includes(f));
      }
      if (draft.ccFromMail !== saved.ccFromMail) body.cc_from_first_mail = draft.ccFromMail;
    }
    save({ kind: 'settings', body }, discard, base);
  };
  const problemAt = (field: string) =>
    field === 'next_number' && nextProblem !== null ? nextProblem : byField[field];
  const option = (scale: 'impact' | 'urgency' | 'priority', code: string) => ({
    value: code,
    label: scaleLabel(t, catalogue, scale, code, locale),
  });
  return (
    <Flex vertical gap={16} data-testid="settings-general">
      {stale && <StaleNotice onReload={discard} />}
      {/* A refusal with no field to point at (QA WP-029 BUG-02); field ones show in place. */}
      {Object.keys(byField).length === 0 && <Problems problems={problems} />}
      <SettingsCard
        title={t('settings.numbering')}
        description={t('settings.numbering_help')}
        testId="settings-numbering"
      >
        <Form layout="vertical" component="div">
          <Flex gap={16} wrap>
            <Form.Item
              label={t('settings.prefix')}
              htmlFor="settings-prefix"
              validateStatus={problemAt('prefix') === undefined ? undefined : 'error'}
              help={
                <FieldHelp
                  problem={problemAt('prefix')}
                  help={t('settings.prefix_help')}
                  testId="settings-numbering-error-prefix"
                />
              }
            >
              <Input
                id="settings-prefix"
                dir="ltr"
                value={draft.prefix}
                count={lengthLimit(6)}
                style={{ width: 140 }}
                onChange={(event) => {
                  set({ prefix: event.target.value.toUpperCase() });
                }}
                data-testid="settings-prefix"
              />
            </Form.Item>
            <Form.Item
              label={t('settings.next_number')}
              htmlFor="settings-next-number"
              validateStatus={problemAt('next_number') === undefined ? undefined : 'error'}
              help={
                <FieldHelp
                  problem={problemAt('next_number')}
                  help={t('settings.next_number_help', { minimum: catalogue.next_number })}
                  testId="settings-numbering-error-next_number"
                />
              }
            >
              <InputNumber
                id="settings-next-number"
                value={draft.next}
                style={{ width: 160 }}
                onChange={(value) => {
                  set({ next: typeof value === 'number' ? value : null });
                }}
                data-testid="settings-next-number"
              />
            </Form.Item>
          </Flex>
          <Typography.Paragraph data-testid="settings-next-id">
            {t('settings.next_id', {
              id: `${draft.prefix.trim().toUpperCase()}-${String(draft.next ?? '')}`,
            })}
          </Typography.Paragraph>
        </Form>
      </SettingsCard>
      <SettingsCard title={t('settings.defaults')} testId="settings-defaults">
        <Form layout="vertical" component="div">
          <Flex gap={16} wrap>
            <Form.Item label={t('settings.default_impact')} htmlFor="settings-default-impact">
              <Select
                id="settings-default-impact"
                value={draft.impact}
                style={{ width: 240 }}
                onChange={(value: string) => {
                  set({ impact: value });
                }}
                options={[
                  { value: NONE, label: t('settings.no_default') },
                  ...IMPACTS.map((c) => option('impact', c)),
                ]}
                data-testid="settings-default-impact"
              />
            </Form.Item>
            <Form.Item label={t('settings.default_urgency')} htmlFor="settings-default-urgency">
              <Select
                id="settings-default-urgency"
                value={draft.urgency}
                style={{ width: 240 }}
                onChange={(value: string) => {
                  set({ urgency: value });
                }}
                options={[
                  { value: NONE, label: t('settings.no_default') },
                  ...URGENCIES.map((c) => option('urgency', c)),
                ]}
                data-testid="settings-default-urgency"
              />
            </Form.Item>
            <Form.Item
              label={t('settings.default_priority')}
              htmlFor="settings-default-priority"
              help={t('settings.default_priority_help')}
            >
              <Select
                id="settings-default-priority"
                value={draft.priority}
                style={{ width: 240 }}
                onChange={(value: General['priority']) => {
                  set({ priority: value });
                }}
                options={PRIORITIES.map((c) => option('priority', c))}
                data-testid="settings-default-priority"
              />
            </Form.Item>
          </Flex>
        </Form>
      </SettingsCard>
      <SettingsCard title={t('settings.automation')} testId="settings-automation">
        <Flex vertical gap={16}>
          <Toggle
            id="settings-auto-status"
            checked={draft.auto}
            onChange={(auto) => {
              set({ auto });
            }}
            title={t('settings.auto_status_on_assign')}
            help={t('settings.auto_status_on_assign_help')}
          />
          <Toggle
            id="settings-keep-following"
            checked={draft.follow}
            onChange={(follow) => {
              set({ follow });
            }}
            title={t('settings.keep_following')}
            help={t('settings.keep_following_help')}
          />
          <Toggle
            id="settings-portal-due-time"
            checked={draft.dueTime}
            onChange={(dueTime) => {
              set({ dueTime });
            }}
            title={t('settings.portal_show_due_time')}
            help={t('settings.portal_show_due_time_help')}
          />
          <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
            <legend>
              <Typography.Text strong>{t('settings.first_response_on')}</Typography.Text>
            </legend>
            <Typography.Paragraph type="secondary">
              {t('settings.first_response_help')}
            </Typography.Paragraph>
            <Checkbox.Group
              value={draft.first}
              onChange={(values) => {
                set({ first: values });
              }}
              options={FIRST_RESPONSE.map((code) => ({
                value: code,
                label: t(`first_response_action.${code}`),
              }))}
              data-testid="settings-first-response"
            />
          </fieldset>
        </Flex>
      </SettingsCard>
      {incidents && (
        <SettingsCard title={t('settings.mail')} testId="settings-mail">
          <Flex vertical gap={16}>
            <Toggle
              id="settings-mail-commands"
              checked={draft.mailCommands}
              onChange={(mailCommands) => {
                set({ mailCommands });
              }}
              title={t('settings.mail_commands')}
              help={t('settings.mail_commands_help')}
            />
            {draft.mailCommands && (
              <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
                <legend>
                  <Typography.Text strong>{t('settings.mail_command_fields')}</Typography.Text>
                </legend>
                <Checkbox.Group
                  value={draft.mailFields}
                  onChange={(values) => {
                    set({ mailFields: values });
                  }}
                  options={MAIL_FIELDS.map((code) => ({
                    value: code,
                    label: t(`mail_command_field.${code}`),
                  }))}
                  data-testid="settings-mail-command-fields"
                />
              </fieldset>
            )}
            <Toggle
              id="settings-cc-from-mail"
              checked={draft.ccFromMail}
              onChange={(ccFromMail) => {
                set({ ccFromMail });
              }}
              title={t('settings.cc_from_first_mail')}
              help={t('settings.cc_from_first_mail_help')}
            />
          </Flex>
        </SettingsCard>
      )}
      <StickySaveBar
        changes={changedKeys.length}
        saving={pending}
        onDiscard={discard}
        onSave={submit}
        testId="settings-general-save"
      />
      <ConflictDialog {...conflictDialog} />
    </Flex>
  );
}

/** A switch with its name and one line of help, the label naming the switch. */
function Toggle({
  id,
  checked,
  onChange,
  title,
  help,
}: {
  id: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  title: string;
  help: string;
}) {
  return (
    <Flex gap={12} align="start">
      <Switch id={id} checked={checked} onChange={onChange} data-testid={id} />
      <label htmlFor={id}>
        <Typography.Text strong>{title}</Typography.Text>
        <br />
        <Typography.Text type="secondary">{help}</Typography.Text>
      </label>
    </Flex>
  );
}

/** A field's problem in place (QA C1), else its help. */
function FieldHelp({ problem, help, testId }: { problem?: string; help: string; testId: string }) {
  return problem === undefined ? (
    help
  ) : (
    <span role="alert" data-testid={testId}>
      {problem}
    </span>
  );
}
