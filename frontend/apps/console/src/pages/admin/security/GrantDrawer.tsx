import {
  Alert,
  App,
  Button,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Select,
  Space,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useCreateSupportGrant,
  type SupportGrantInput,
  type SupportGrantMade,
} from '@supportx/api-client';
import {
  EditDrawer,
  FormProblem,
  lengthLimit,
  markHandled,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

const DEFAULT_HOURS = 24;
const MAX_HOURS = 72; // D-173: 72 hours at most in all, extensions included

interface Values {
  engineer_name: string;
  engineer_email: string;
  reason: string;
  ticket_ref?: string;
  access: SupportGrantInput['access'];
  change_reason?: string;
  unmask_personal: boolean;
  hours: number;
  ip_allowlist: string[];
  verification: SupportGrantInput['verification'];
  confirmation_note?: string;
}

const INITIAL: Partial<Values> = {
  access: 'view', // D-173 (6): view only is preselected
  unmask_personal: false,
  hours: DEFAULT_HOURS,
  ip_allowlist: [],
  verification: 'email',
};

function body(values: Values): SupportGrantInput {
  const text = (value: string | undefined) => {
    const trimmed = (value ?? '').trim();
    return trimmed === '' ? null : trimmed;
  };
  return {
    engineer_name: values.engineer_name.trim(),
    engineer_email: values.engineer_email.trim(),
    reason: values.reason.trim(),
    ticket_ref: text(values.ticket_ref),
    access: values.access,
    change_reason: values.access === 'view_and_change' ? text(values.change_reason) : null,
    unmask_personal: values.unmask_personal,
    hours: values.hours,
    ip_allowlist: values.ip_allowlist,
    verification: values.verification,
    confirmation_note:
      values.verification === 'out_of_band' ? text(values.confirmation_note) : null,
  };
}

/**
 * The one time the engineer's temporary password is shown (D-177, the call-back path). It lives
 * in this dialog's props only; closing it resets the mutation, so no copy stays anywhere.
 */
export function SupportPasswordDialog({
  made,
  onClose,
}: {
  made: SupportGrantMade;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  return (
    <Modal
      open
      title={t('vendor_support.password.title')}
      closable={false}
      maskClosable={false}
      keyboard={false}
      footer={
        <Button type="primary" onClick={onClose} data-testid="vendor-support-password-done">
          {t('vendor_support.password.done')}
        </Button>
      }
      data-testid="vendor-support-password"
    >
      {made.one_time_password == null ? (
        <Alert type="warning" showIcon message={t('vendor_support.password.replay')} />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Paragraph>
            {t('vendor_support.password.explain', { name: made.engineer_name })}
          </Typography.Paragraph>
          <Space.Compact style={{ width: '100%' }}>
            <Input
              readOnly
              value={made.one_time_password}
              dir="ltr"
              aria-label={t('vendor_support.password.title')}
              data-testid="vendor-support-password-text"
              style={{ fontFamily: 'monospace' }}
            />
            <Button
              data-testid="vendor-support-password-copy"
              onClick={() => {
                // On click only, never automatically (lane B (4)).
                void navigator.clipboard
                  .writeText(made.one_time_password ?? '')
                  .then(() => void message.success(t('vendor_support.password.copied')));
              }}
            >
              {t('vendor_support.password.copy')}
            </Button>
          </Space.Compact>
          <Typography.Text type="secondary">{t('vendor_support.password.after')}</Typography.Text>
        </Space>
      )}
    </Modal>
  );
}

/** Grant access to one named Extravis engineer (template B; the API checks every rule again). */
export function GrantDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useLabel();
  const { message } = App.useApp();
  const [form] = Form.useForm<Values>();
  const create = useCreateSupportGrant();
  const problem = useFormProblem();
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [made, setMade] = useState<SupportGrantMade | null>(null);
  const access = Form.useWatch('access', form);
  const verification = Form.useWatch('verification', form);

  const close = () => {
    form.resetFields();
    problem.clear();
    setKey(crypto.randomUUID());
    onClose();
  };
  const submit = async () => {
    problem.clear();
    const values = await form.validateFields();
    create.mutate(
      { body: body(values), key },
      {
        onSuccess: (result) => {
          close();
          if (result.one_time_password != null) {
            setMade(result);
          } else {
            void message.success(t('vendor_support.grant.link_sent'));
          }
        },
        onError: (error) => {
          if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
            markHandled(error);
            form.setFields(
              error.fieldErrors.map((f) => ({
                name: f.field.replace(/^body\./, '') as keyof Values,
                errors: [t(f.message_key, f.params ?? {})],
              })),
            );
            return;
          }
          problem.show(error);
        },
      },
    );
  };
  return (
    <>
      <EditDrawer
        open={open}
        title={t('vendor_support.grant.title')}
        okText={t('vendor_support.grant.submit')}
        saving={create.isPending}
        onCancel={close}
        onOk={() => {
          void submit();
        }}
        testId="vendor-support-grant-drawer"
      >
        <FormProblem problem={problem} />
        <Form<Values> form={form} layout="vertical" initialValues={INITIAL} requiredMark>
          <Typography.Title level={5}>{t('vendor_support.grant.who')}</Typography.Title>
          <Form.Item
            name="engineer_name"
            label={t('vendor_support.field.engineer_name')}
            rules={[{ required: true, whitespace: true, message: t('errors.field.required') }]}
          >
            <Input count={lengthLimit(200)} data-testid="vendor-support-name" />
          </Form.Item>
          <Form.Item
            name="engineer_email"
            label={t('vendor_support.field.engineer_email')}
            extra={t('vendor_support.field.engineer_email_help')}
            rules={[{ required: true, whitespace: true, message: t('errors.field.required') }]}
          >
            <Input
              type="email"
              dir="ltr"
              count={lengthLimit(320)}
              data-testid="vendor-support-email"
            />
          </Form.Item>
          <Typography.Title level={5}>{t('vendor_support.grant.why')}</Typography.Title>
          <Form.Item
            name="reason"
            label={t('vendor_support.field.reason')}
            rules={[{ required: true, whitespace: true, message: t('errors.field.required') }]}
          >
            <Input.TextArea autoSize={{ minRows: 2 }} data-testid="vendor-support-reason" />
          </Form.Item>
          <Form.Item name="ticket_ref" label={t('vendor_support.field.ticket_ref')}>
            <Input count={lengthLimit(100)} dir="ltr" data-testid="vendor-support-ticket" />
          </Form.Item>
          <Typography.Title level={5}>{t('vendor_support.grant.what')}</Typography.Title>
          <Form.Item name="access" label={t('vendor_support.field.access')}>
            <Radio.Group data-testid="vendor-support-access">
              <Space direction="vertical">
                <Radio value="view">
                  {t('support_grant_access.view')}
                  <Typography.Text type="secondary">
                    {' '}
                    {t('vendor_support.access.view_help')}
                  </Typography.Text>
                </Radio>
                <Radio value="view_and_change">
                  {t('support_grant_access.view_and_change')}
                  <Typography.Text type="secondary">
                    {' '}
                    {t('vendor_support.access.change_help')}
                  </Typography.Text>
                </Radio>
              </Space>
            </Radio.Group>
          </Form.Item>
          {access === 'view_and_change' && (
            <Form.Item
              name="change_reason"
              label={t('vendor_support.field.change_reason')}
              rules={[{ required: true, whitespace: true, message: t('errors.field.required') }]}
            >
              <Input.TextArea
                autoSize={{ minRows: 2 }}
                data-testid="vendor-support-change-reason"
              />
            </Form.Item>
          )}
          <Form.Item
            name="unmask_personal"
            valuePropName="checked"
            extra={t('vendor_support.field.unmask_help')}
          >
            <Checkbox data-testid="vendor-support-unmask">
              {t('vendor_support.field.unmask')}
            </Checkbox>
          </Form.Item>
          <Typography.Title level={5}>{t('vendor_support.grant.how_long')}</Typography.Title>
          <Form.Item
            name="hours"
            label={t('vendor_support.field.hours')}
            extra={t('vendor_support.field.hours_help', { max: MAX_HOURS })}
            rules={[{ required: true, message: t('errors.field.required') }]}
          >
            <InputNumber
              min={1}
              max={MAX_HOURS}
              precision={0}
              suffix={t('vendor_support.hours_unit')}
              style={{ width: 168 }}
              data-testid="vendor-support-hours"
            />
          </Form.Item>
          <Form.Item
            name="ip_allowlist"
            label={t('vendor_support.field.ip_allowlist')}
            extra={t('vendor_support.field.ip_allowlist_help')}
          >
            <Select
              mode="tags"
              open={false}
              tokenSeparators={[',', ' ']}
              style={{ direction: 'ltr' }}
              data-testid="vendor-support-ips"
            />
          </Form.Item>
          <Typography.Title level={5}>{t('vendor_support.grant.verification')}</Typography.Title>
          <Form.Item name="verification">
            <Radio.Group data-testid="vendor-support-verification">
              <Space direction="vertical">
                <Radio value="email">{t('vendor_support.verification.email')}</Radio>
                <Radio value="out_of_band">{t('vendor_support.verification.out_of_band')}</Radio>
              </Space>
            </Radio.Group>
          </Form.Item>
          {verification === 'out_of_band' && (
            <Form.Item
              name="confirmation_note"
              label={t('vendor_support.field.confirmation_note')}
              extra={t('vendor_support.field.confirmation_note_help')}
              rules={[{ required: true, whitespace: true, message: t('errors.field.required') }]}
            >
              <Input.TextArea autoSize={{ minRows: 2 }} data-testid="vendor-support-note" />
            </Form.Item>
          )}
        </Form>
      </EditDrawer>
      {made !== null && (
        <SupportPasswordDialog
          made={made}
          onClose={() => {
            setMade(null);
            create.reset(); // the answer (and its password) is gone from the mutation too
          }}
        />
      )}
    </>
  );
}
