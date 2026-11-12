import { Alert, App, Button, Form, Input, Modal, Select, Space, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';

import {
  ApiError,
  useCreateIncident,
  useCustomFields,
  useIncidentCatalogue,
  useIncidentTemplates,
  type IncidentInput,
  type IncidentTemplate,
} from '@supportx/api-client';
import { formFieldOf } from '@supportx/forms';
import { useListFormat } from '@supportx/labels';
import { lengthLimit, reportError, useAppearance, useLabel } from '@supportx/ui';

import { fieldName } from '../customFields/values';
import { scaleLabel } from './labels';
import { UserPicker } from './pickers';

// Quick create (WP-046a S5c; REQ-INC-018): an incident with a subject, a requester and, if the
// technician wants, a priority, without leaving the list. It is the same create as the full form:
// the default template's starting values are sent, and the server applies the template's rules,
// so a rule that needs another field refuses it and the dialog names that field (AC2) with a way
// to the full form. The new row appears in the list live, like any other new incident (AC1).

const PRIORITIES = ['p1', 'p2', 'p3', 'p4', 'p5'] as const;
const OWN = new Set(['subject', 'requester_id', 'priority', 'priority_reason']);

/** The template's starting values as the create takes them (custom ones under `custom`). */
function startingValues(template: IncidentTemplate | undefined): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  const custom: Record<string, unknown> = {};
  for (const [name, value] of Object.entries(template?.defaults ?? {})) {
    if (value === null || value === undefined || value === '') continue;
    if (name.startsWith('custom.')) custom[name.slice('custom.'.length)] = value;
    else if (!OWN.has(name)) body[name] = value;
  }
  if (Object.keys(custom).length > 0) body.custom = custom;
  return body;
}

export function QuickCreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useLabel();
  const listFormat = useListFormat();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const templates = useIncidentTemplates(open);
  const catalogue = useIncidentCatalogue();
  const customFields = useCustomFields('incident');
  const create = useCreateIncident();
  const template = useMemo(() => {
    const offered = (templates.data ?? []).filter((x) => !x.disabled);
    return offered.find((x) => x.is_default) ?? offered[0];
  }, [templates.data]);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [subject, setSubject] = useState('');
  const [requester, setRequester] = useState<string | null>(null);
  const [priority, setPriority] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [errors, setErrors] = useState<Map<string, string>>(new Map());
  const fieldLabel = (name: string) => {
    if (!name.startsWith('custom.')) return t(`work_item.field.${name}`);
    const found = customFields.data?.find((f) => `custom.${f.key}` === name);
    return found === undefined ? t('custom_fields.unknown_field') : fieldName(found, locale);
  };
  // Fields a rule or the template needs that this dialog does not have (AC2).
  const elsewhere = [...errors.keys()].filter((name) => !OWN.has(name));
  const errorOf = (name: string) => {
    const code = errors.get(name);
    return code === undefined ? undefined : t(`errors.field.${code}`);
  };

  const reset = () => {
    setSubject('');
    setRequester(null);
    setPriority(null);
    setReason('');
    setErrors(new Map());
    setKey(crypto.randomUUID());
  };
  const close = () => {
    reset();
    onClose();
  };
  const submit = () => {
    const missing = new Map<string, string>();
    if (subject.trim() === '') missing.set('subject', 'required');
    if (requester === null) missing.set('requester_id', 'required');
    if (priority !== null && reason.trim() === '') missing.set('priority_reason', 'required');
    if (missing.size > 0) {
      setErrors(missing);
      return;
    }
    const body = {
      ...startingValues(template),
      subject: subject.trim(),
      requester_id: requester,
      ...(template === undefined ? {} : { template_id: template.id }),
      ...(priority === null ? {} : { priority, priority_reason: reason.trim() }),
    } as unknown as IncidentInput; // the API's own shape: a template's values are any field's
    create.mutate(
      { body, key },
      {
        onSuccess: (saved) => {
          void message.success(t('incidents.quick.made', { id: saved.display_id }));
          close();
        },
        onError: (error) => {
          if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
            setErrors(new Map(error.fieldErrors.map((e) => [formFieldOf(e.field), e.code])));
            setKey(crypto.randomUUID()); // a fixed retry is a new create
            return;
          }
          reportError(error);
        },
      },
    );
  };
  const fullForm = () => {
    const params = new URLSearchParams();
    if (template !== undefined) params.set('template', template.id);
    if (requester !== null) params.set('requester', requester);
    close();
    void navigate(`/incidents/new?${params.toString()}`);
  };

  return (
    <Modal
      open={open}
      title={t('incidents.quick.title')}
      okText={t('incidents.quick.create')}
      cancelText={t('actions.cancel')}
      onOk={submit}
      onCancel={close}
      confirmLoading={create.isPending}
      okButtonProps={{ 'data-testid': 'inc-quick-create' }}
      data-testid="inc-quick"
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">{t('incidents.quick.help')}</Typography.Paragraph>
      {elsewhere.length > 0 && (
        <Alert
          type="warning"
          showIcon
          role="alert"
          style={{ marginBottom: 16 }}
          message={t('incidents.quick.needs', {
            fields: listFormat(elsewhere.map(fieldLabel), 'conjunction'),
          })}
          action={
            <Button size="small" onClick={fullForm} data-testid="inc-quick-full">
              {t('incidents.quick.full_form')}
            </Button>
          }
          data-testid="inc-quick-needs"
        />
      )}
      <Form layout="vertical" component="div">
        <Form.Item
          label={t('work_item.field.subject')}
          htmlFor="inc-quick-subject"
          required
          validateStatus={errors.has('subject') ? 'error' : undefined}
          help={errorOf('subject')}
        >
          <Input
            id="inc-quick-subject"
            dir="auto"
            autoFocus
            count={lengthLimit(250, true)}
            value={subject}
            onChange={(event) => {
              setSubject(event.target.value);
            }}
            onPressEnter={submit}
            data-testid="inc-quick-subject"
          />
        </Form.Item>
        <Form.Item
          label={t('work_item.field.requester_id')}
          htmlFor="inc-quick-requester"
          required
          validateStatus={errors.has('requester_id') ? 'error' : undefined}
          help={errorOf('requester_id')}
        >
          <UserPicker
            id="inc-quick-requester"
            value={requester}
            onChange={setRequester}
            testId="inc-quick-requester"
            ariaLabel={t('work_item.field.requester_id')}
          />
        </Form.Item>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Form.Item
            label={t('work_item.field.priority')}
            htmlFor="inc-quick-priority"
            help={t('incidents.quick.priority_help')}
          >
            <Select
              id="inc-quick-priority"
              allowClear
              value={priority ?? undefined}
              placeholder={t('incidents.priority_from_matrix')}
              onChange={(next: string | undefined) => {
                setPriority(next ?? null);
              }}
              options={PRIORITIES.map((p) => ({
                value: p,
                label: scaleLabel(t, catalogue.data, 'priority', p, locale),
              }))}
              data-testid="inc-quick-priority"
            />
          </Form.Item>
          {priority !== null && (
            <Form.Item
              label={t('work_item.field.priority_reason')}
              htmlFor="inc-quick-reason"
              required
              validateStatus={errors.has('priority_reason') ? 'error' : undefined}
              help={errorOf('priority_reason')}
            >
              <Input
                id="inc-quick-reason"
                dir="auto"
                count={lengthLimit(500)}
                value={reason}
                onChange={(event) => {
                  setReason(event.target.value);
                }}
                data-testid="inc-quick-reason"
              />
            </Form.Item>
          )}
        </Space>
      </Form>
    </Modal>
  );
}
