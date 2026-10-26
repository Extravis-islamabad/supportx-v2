import {
  Alert,
  Button,
  Card,
  Checkbox,
  Flex,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Typography,
} from 'antd';

import type { IncidentCatalogue } from '@supportx/api-client';
import { useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { scaleLabel } from '../../incidents/labels';
import { useDraft, useSettingsSave } from './helpers';
import { Problems } from './shared';

const IMPACTS = ['one_person', 'team', 'department_or_site', 'organisation'] as const;
const URGENCIES = ['low', 'medium', 'high', 'critical'] as const;
const PRIORITIES = ['p1', 'p2', 'p3', 'p4'] as const;
const FIRST_RESPONSE = ['reply', 'public_note', 'private_note'] as const;
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

export function GeneralTab({ catalogue }: { catalogue: IncidentCatalogue }) {
  return (
    <Flex vertical gap={16}>
      <NumberingCard catalogue={catalogue} />
      <DefaultsCard catalogue={catalogue} />
      <AutomationCard catalogue={catalogue} />
    </Flex>
  );
}

/** Prefix and next number (REQ-WI-002 AC4, REQ-ADM-045). */
function NumberingCard({ catalogue }: { catalogue: IncidentCatalogue }) {
  const t = useLabel();
  const { save, pending, problems } = useSettingsSave();
  const source = { prefix: catalogue.prefix, next: catalogue.next_number };
  const { draft, edit, reset, stale, dirty } = useDraft(source, catalogue.version);
  const submit = () => {
    const prefix = draft.prefix.trim().toUpperCase();
    const afterPrefix = () => {
      if (draft.next !== catalogue.next_number) {
        save({ kind: 'numbering', nextNumber: draft.next }, reset);
      } else {
        reset();
      }
    };
    if (prefix !== catalogue.prefix) save({ kind: 'settings', body: { prefix } }, afterPrefix);
    else afterPrefix();
  };
  return (
    <Card title={t('settings.numbering')} data-testid="settings-numbering">
      {stale && <StaleNotice onReload={reset} />}
      <Problems problems={problems} />
      <Typography.Paragraph type="secondary">{t('settings.numbering_help')}</Typography.Paragraph>
      <Form layout="vertical" component="div">
        <Flex gap={16} wrap>
          <Form.Item
            label={t('settings.prefix')}
            htmlFor="settings-prefix"
            help={t('settings.prefix_help')}
          >
            <Input
              id="settings-prefix"
              dir="ltr"
              value={draft.prefix}
              maxLength={6}
              style={{ width: 140 }}
              onChange={(event) => {
                edit({ ...draft, prefix: event.target.value.toUpperCase() });
              }}
              data-testid="settings-prefix"
            />
          </Form.Item>
          <Form.Item
            label={t('settings.next_number')}
            htmlFor="settings-next-number"
            help={t('settings.next_number_help', { minimum: catalogue.next_number })}
          >
            <InputNumber
              id="settings-next-number"
              min={1}
              precision={0}
              value={draft.next}
              style={{ width: 160 }}
              onChange={(value) => {
                edit({ ...draft, next: typeof value === 'number' ? value : catalogue.next_number });
              }}
              data-testid="settings-next-number"
            />
          </Form.Item>
        </Flex>
        <Typography.Paragraph data-testid="settings-next-id">
          {t('settings.next_id', {
            id: `${draft.prefix.trim().toUpperCase()}-${String(draft.next)}`,
          })}
        </Typography.Paragraph>
        <Space>
          <WriteButton
            type="primary"
            loading={pending}
            disabled={!dirty}
            onClick={submit}
            data-testid="settings-numbering-save"
          >
            {t('actions.save')}
          </WriteButton>
          <Button disabled={!dirty} onClick={reset}>
            {t('actions.reset')}
          </Button>
        </Space>
      </Form>
    </Card>
  );
}

/** What the create form starts with, and the priority when nothing is known (REQ-INC-011). */
function DefaultsCard({ catalogue }: { catalogue: IncidentCatalogue }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { save, pending, problems } = useSettingsSave();
  const source = {
    impact: catalogue.default_impact ?? NONE,
    urgency: catalogue.default_urgency ?? NONE,
    priority: catalogue.default_priority,
  };
  const { draft, edit, reset, stale, dirty } = useDraft(source, catalogue.version);
  const option = (scale: 'impact' | 'urgency' | 'priority', code: string) => ({
    value: code,
    label: scaleLabel(t, catalogue, scale, code, locale),
  });
  return (
    <Card title={t('settings.defaults')} data-testid="settings-defaults">
      {stale && <StaleNotice onReload={reset} />}
      <Problems problems={problems} />
      <Form layout="vertical" component="div">
        <Flex gap={16} wrap>
          <Form.Item label={t('settings.default_impact')} htmlFor="settings-default-impact">
            <Select
              id="settings-default-impact"
              value={draft.impact}
              style={{ width: 240 }}
              onChange={(value: string) => {
                edit({ ...draft, impact: value });
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
                edit({ ...draft, urgency: value });
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
              onChange={(value: typeof draft.priority) => {
                edit({ ...draft, priority: value });
              }}
              options={PRIORITIES.map((c) => option('priority', c))}
              data-testid="settings-default-priority"
            />
          </Form.Item>
        </Flex>
        <Space>
          <WriteButton
            type="primary"
            loading={pending}
            disabled={!dirty}
            onClick={() => {
              save(
                {
                  kind: 'settings',
                  body: {
                    default_impact: draft.impact === NONE ? null : (draft.impact as never),
                    default_urgency: draft.urgency === NONE ? null : (draft.urgency as never),
                    default_priority: draft.priority,
                  },
                },
                reset,
              );
            }}
            data-testid="settings-defaults-save"
          >
            {t('actions.save')}
          </WriteButton>
          <Button disabled={!dirty} onClick={reset}>
            {t('actions.reset')}
          </Button>
        </Space>
      </Form>
    </Card>
  );
}

/** Automatic status move, keep following after a hand-over (D-068), first response (D-079). */
function AutomationCard({ catalogue }: { catalogue: IncidentCatalogue }) {
  const t = useLabel();
  const { save, pending, problems } = useSettingsSave();
  const source = {
    auto: catalogue.auto_status_on_assign,
    follow: catalogue.keep_following_on_handover,
    first: [...catalogue.first_response_on] as string[],
  };
  const { draft, edit, reset, stale, dirty } = useDraft(source, catalogue.version);
  return (
    <Card title={t('settings.automation')} data-testid="settings-automation">
      {stale && <StaleNotice onReload={reset} />}
      <Problems problems={problems} />
      <Flex vertical gap={16}>
        <Flex gap={12} align="start">
          <Switch
            id="settings-auto-status"
            checked={draft.auto}
            onChange={(checked) => {
              edit({ ...draft, auto: checked });
            }}
            data-testid="settings-auto-status"
          />
          <label htmlFor="settings-auto-status">
            <Typography.Text strong>{t('settings.auto_status_on_assign')}</Typography.Text>
            <br />
            <Typography.Text type="secondary">
              {t('settings.auto_status_on_assign_help')}
            </Typography.Text>
          </label>
        </Flex>
        <Flex gap={12} align="start">
          <Switch
            id="settings-keep-following"
            checked={draft.follow}
            onChange={(checked) => {
              edit({ ...draft, follow: checked });
            }}
            data-testid="settings-keep-following"
          />
          <label htmlFor="settings-keep-following">
            <Typography.Text strong>{t('settings.keep_following')}</Typography.Text>
            <br />
            <Typography.Text type="secondary">{t('settings.keep_following_help')}</Typography.Text>
          </label>
        </Flex>
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
              edit({ ...draft, first: values });
            }}
            options={FIRST_RESPONSE.map((code) => ({
              value: code,
              label: t(`first_response_action.${code}`),
            }))}
            data-testid="settings-first-response"
          />
        </fieldset>
        <Space>
          <WriteButton
            type="primary"
            loading={pending}
            disabled={!dirty}
            onClick={() => {
              save(
                {
                  kind: 'settings',
                  body: {
                    auto_status_on_assign: draft.auto,
                    keep_following_on_handover: draft.follow,
                    first_response_on: draft.first as never,
                  },
                },
                reset,
              );
            }}
            data-testid="settings-automation-save"
          >
            {t('actions.save')}
          </WriteButton>
          <Button disabled={!dirty} onClick={reset}>
            {t('actions.reset')}
          </Button>
        </Space>
      </Flex>
    </Card>
  );
}
