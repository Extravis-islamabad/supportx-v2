import {
  App,
  Button,
  Card,
  Checkbox,
  Col,
  Form,
  Input,
  Radio,
  Row,
  Select,
  Space,
  Typography,
} from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { ApiError, useCreateIncident, useIncidentCatalogue, useUnits } from '@supportx/api-client';
import { applyServerErrors, FormField, useForm, zodResolver } from '@supportx/forms';
import {
  NoAccess,
  reportError,
  RichTextField,
  useAccess,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { HandOverWarning } from './assign';
import { bodyOf, EMPTY, FIELDS, previewPriority, schema, SUBJECT_MAX, type Values } from './form';
import { CategoryPicker, GroupPicker, SitePicker, TechnicianPicker, UserPicker } from './pickers';
import { PriorityTag } from './tags';

const IMPACTS = ['one_person', 'team', 'department_or_site', 'organisation'] as const;
const URGENCIES = ['low', 'medium', 'high', 'critical'] as const;
const PRIORITIES = ['p1', 'p2', 'p3', 'p4'] as const;

/**
 * Log an incident (REQ-INC-017). One Idempotency-Key per form, so a double click or a retried
 * request creates one incident (REQ-WI-008); the save button shows progress and ignores repeat
 * clicks. Suggestions and help never open inside the form flow, so nothing moves under the
 * pointer (REQ-WI-012). Priority is shown live from the matrix and can be set by hand with a
 * reason by those who may (REQ-INC-009/010).
 */
export function NewIncidentPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const { can } = useAccess();
  const create = useCreateIncident();
  const catalogue = useIncidentCatalogue();
  const groups = useUnits('groups');
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: EMPTY });
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [another, setAnother] = useState(false);
  const [keepRequester, setKeepRequester] = useState(false);
  const [handover, setHandover] = useState<Values | null>(null);
  const impact = form.watch('impact');
  const urgency = form.watch('urgency');
  const group = form.watch('group_id');
  const manual = form.watch('priority');
  const preview = previewPriority(catalogue.data, impact, urgency);
  const canAssign = can('incidents.assign');
  const canPriority = can('incidents.change_priority');

  if (!can('incidents.create')) return <NoAccess titleKey="nav.incidents" />;
  const send = (values: Values, confirm: boolean) => {
    create.mutate(
      { body: bodyOf(values, confirm), key: confirm ? `${key}-confirmed` : key },
      {
        onSuccess: (saved) => {
          setHandover(null);
          void message.success(t('incidents.created', { id: saved.display_id }));
          if (!saved.visible) {
            void navigate('/incidents', { replace: true });
            return;
          }
          if (another) {
            const requester = keepRequester ? values.requester_id : null;
            form.reset({ ...EMPTY, requester_id: requester });
            setKey(crypto.randomUUID());
            return;
          }
          void navigate(`/incidents/${saved.id}`, { replace: true });
        },
        onError: (error) => {
          if (error instanceof ApiError && error.code === 'would_lose_access') {
            setHandover(values);
            return;
          }
          setKey(crypto.randomUUID()); // corrected input is a new request
          if (!applyServerErrors(error, form.setError, FIELDS)) reportError(error);
        },
      },
    );
  };
  const save = form.handleSubmit((values) => {
    send(values, false);
  });
  const control = form.control;
  const groupName =
    groups.data?.find((g) => g.id === handover?.group_id)?.name ?? t('incidents.no_group');
  return (
    <Space direction="vertical" size="large" style={{ width: '100%', maxWidth: 1100 }}>
      <Typography.Title level={1}>{t('incidents.new')}</Typography.Title>
      <Card>
        <Form layout="vertical" component="div" data-testid="inc-form">
          <FormField
            control={control}
            name="subject"
            labelKey="work_item.field.subject"
            render={(field) => (
              <Input {...field} maxLength={SUBJECT_MAX} data-testid="inc-subject" />
            )}
          />
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <FormField
                control={control}
                name="requester_id"
                labelKey="work_item.field.requester_id"
                render={(field) => (
                  <UserPicker
                    id={field.id}
                    value={field.value}
                    onChange={field.onChange}
                    testId="inc-requester"
                    ariaLabel={t('work_item.field.requester_id')}
                  />
                )}
              />
            </Col>
            <Col xs={24} md={12}>
              <FormField
                control={control}
                name="on_behalf_of_id"
                labelKey="work_item.field.on_behalf_of_id"
                render={(field) => (
                  <UserPicker
                    id={field.id}
                    value={field.value}
                    onChange={field.onChange}
                    testId="inc-on-behalf"
                    ariaLabel={t('work_item.field.on_behalf_of_id')}
                  />
                )}
              />
            </Col>
            <Col xs={24} md={8}>
              <FormField
                control={control}
                name="channel"
                labelKey="work_item.field.channel"
                render={(field) => (
                  <Radio.Group
                    id={field.id}
                    value={field.value}
                    onChange={(event) => {
                      field.onChange(event.target.value);
                    }}
                    optionType="button"
                    options={[
                      { value: 'phone', label: t('work_item_channel.phone') },
                      { value: 'walk_up', label: t('work_item_channel.walk_up') },
                    ]}
                    data-testid="inc-channel"
                  />
                )}
              />
            </Col>
            <Col xs={24} md={8}>
              <FormField
                control={control}
                name="site_id"
                labelKey="work_item.field.site_id"
                helpKey="incidents.site_help"
                render={(field) => (
                  <SitePicker
                    id={field.id}
                    value={field.value}
                    onChange={field.onChange}
                    testId="inc-site"
                    ariaLabel={t('work_item.field.site_id')}
                  />
                )}
              />
            </Col>
            <Col xs={24} md={8}>
              <FormField
                control={control}
                name="category_id"
                labelKey="work_item.field.category_id"
                render={(field) => (
                  <CategoryPicker
                    id={field.id}
                    value={field.value}
                    onChange={field.onChange}
                    testId="inc-category"
                    ariaLabel={t('work_item.field.category_id')}
                  />
                )}
              />
            </Col>
            {canAssign && (
              <>
                <Col xs={24} md={12}>
                  <FormField
                    control={control}
                    name="group_id"
                    labelKey="work_item.field.group_id"
                    render={(field) => (
                      <GroupPicker
                        id={field.id}
                        value={field.value}
                        onChange={(next) => {
                          field.onChange(next);
                          form.setValue('technician_id', null);
                        }}
                        testId="inc-group"
                        ariaLabel={t('work_item.field.group_id')}
                      />
                    )}
                  />
                </Col>
                <Col xs={24} md={12}>
                  <FormField
                    control={control}
                    name="technician_id"
                    labelKey="work_item.field.technician_id"
                    render={(field) => (
                      <TechnicianPicker
                        id={field.id}
                        groupId={group}
                        value={field.value}
                        onChange={field.onChange}
                        testId="inc-technician"
                        ariaLabel={t('work_item.field.technician_id')}
                      />
                    )}
                  />
                </Col>
              </>
            )}
            <Col xs={24} md={8}>
              <FormField
                control={control}
                name="impact"
                labelKey="work_item.field.impact"
                render={(field) => (
                  <Select
                    id={field.id}
                    allowClear
                    value={field.value ?? undefined}
                    onChange={(next: string | undefined) => {
                      field.onChange(next ?? null);
                    }}
                    options={IMPACTS.map((v) => ({ value: v, label: t(`impact.${v}`) }))}
                    data-testid="inc-impact"
                  />
                )}
              />
            </Col>
            <Col xs={24} md={8}>
              <FormField
                control={control}
                name="urgency"
                labelKey="work_item.field.urgency"
                render={(field) => (
                  <Select
                    id={field.id}
                    allowClear
                    value={field.value ?? undefined}
                    onChange={(next: string | undefined) => {
                      field.onChange(next ?? null);
                    }}
                    options={URGENCIES.map((v) => ({ value: v, label: t(`urgency.${v}`) }))}
                    data-testid="inc-urgency"
                  />
                )}
              />
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label={t('work_item.field.priority')}>
                <Space direction="vertical" style={{ width: '100%' }}>
                  <span data-testid="inc-priority-preview">
                    {manual === null && preview !== null && (
                      <PriorityTag priority={preview.priority as 'p1'} source={preview.source} />
                    )}
                  </span>
                  {canPriority && (
                    <Select
                      aria-label={t('incidents.priority_override')}
                      value={manual ?? ''}
                      onChange={(next: string) => {
                        form.setValue('priority', next === '' ? null : next);
                      }}
                      options={[
                        { value: '', label: t('incidents.priority_from_matrix') },
                        ...PRIORITIES.map((p) => ({ value: p, label: t(`priority.${p}`) })),
                      ]}
                      data-testid="inc-priority-override"
                    />
                  )}
                </Space>
              </Form.Item>
            </Col>
            {manual !== null && (
              <Col xs={24}>
                <FormField
                  control={control}
                  name="priority_reason"
                  labelKey="work_item.field.priority_reason"
                  render={(field) => (
                    <Input {...field} maxLength={500} data-testid="inc-priority-reason" />
                  )}
                />
              </Col>
            )}
          </Row>
          <FormField
            control={control}
            name="description"
            labelKey="work_item.field.description"
            render={(field) => (
              <RichTextField
                id={field.id}
                label={t('work_item.field.description')}
                value={field.value}
                onChange={field.onChange}
                testId="inc-description-editor"
              />
            )}
          />
          <FormField
            control={control}
            name="tags"
            labelKey="work_item.field.tags"
            render={(field) => (
              <Select
                id={field.id}
                mode="tags"
                value={field.value}
                onChange={field.onChange}
                tokenSeparators={[',']}
                data-testid="inc-tags"
              />
            )}
          />
          <Space wrap>
            <WriteButton
              type="primary"
              loading={create.isPending}
              disabled={create.isPending}
              onClick={() => void save()}
              data-testid="inc-save"
            >
              {t('incidents.save')}
            </WriteButton>
            <Button onClick={() => void navigate('/incidents')}>{t('actions.cancel')}</Button>
            <Checkbox
              checked={another}
              onChange={(event) => {
                setAnother(event.target.checked);
              }}
              data-testid="inc-another"
            >
              {t('incidents.create_another')}
            </Checkbox>
            {another && (
              <Checkbox
                checked={keepRequester}
                onChange={(event) => {
                  setKeepRequester(event.target.checked);
                }}
                data-testid="inc-keep-requester"
              >
                {t('incidents.keep_requester')}
              </Checkbox>
            )}
          </Space>
        </Form>
      </Card>
      <HandOverWarning
        open={handover !== null}
        displayId={t('incidents.this_incident')}
        group={groupName}
        pending={create.isPending}
        onCancel={() => {
          setHandover(null);
        }}
        onConfirm={() => {
          if (handover !== null) send(handover, true);
        }}
      />
    </Space>
  );
}
