import { App, Card, Checkbox, Flex, Form, Input, Select, Space, Typography } from 'antd';
import { useEffect, useMemo } from 'react';

import {
  type TenantSettings,
  type TenantSettingsInput,
  useSaveTenantSettings,
  useTenantSettings,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  NoAccess,
  PageHeader,
  reportError,
  useAccess,
  useAppearance,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { showFieldErrors } from '../knowledge/formErrors';

// WP-042 (REQ-ADM-049, 050, 052): Admin › Instance settings. The defaults for people and sites,
// the base currency (chosen once; a change asks first) and the languages offered (English
// always). Names of time zones, countries, currencies and months come from the browser's own
// data in the person's language.

const LANGUAGES = ['en', 'ar', 'ur'] as const;
const WEEK_STARTS = ['monday', 'sunday', 'saturday'] as const;
const DATE_FORMATS = ['dd/mm/yyyy', 'mm/dd/yyyy', 'yyyy-mm-dd', 'dd.mm.yyyy'] as const;
const TIME_FORMATS = ['24h', '12h'] as const;
const COUNTRIES =
  'AE AF AL AM AO AR AT AU AZ BA BD BE BG BH BR BY CA CH CL CN CO CZ DE DK DZ EE EG ES ET FI FR GB GE GH GR HK HR HU ID IE IL IN IQ IR IS IT JO JP KE KG KR KW KZ LB LK LT LU LV LY MA MX MY NG NL NO NP NZ OM PE PH PK PL PS PT QA RO RS RU SA SD SE SG SI SK SY TH TN TR TW TZ UA UG US UZ VN YE ZA'.split(
    ' ',
  );

type FormValues = Omit<TenantSettings, 'version'>;

function useNames(locale: string) {
  return useMemo(() => {
    const region = new Intl.DisplayNames([locale], { type: 'region' });
    const currency = new Intl.DisplayNames([locale], { type: 'currency' });
    const month = new Intl.DateTimeFormat(locale, { month: 'long' });
    return {
      zones: Intl.supportedValuesOf('timeZone'),
      currencies: Intl.supportedValuesOf('currency'),
      region: (code: string) => region.of(code) ?? code,
      currency: (code: string) => `${currency.of(code) ?? code} (${code})`,
      month: (n: number) => month.format(new Date(Date.UTC(2026, n - 1, 15))),
    };
  }, [locale]);
}

export function InstanceSettingsPage() {
  const t = useLabel();
  const { can } = useAccess();
  const { intlLocale } = useAppearance();
  const { modal, message } = App.useApp();
  const allowed = can('config.organisation') || can('settings.manage');
  const settings = useTenantSettings(allowed);
  const save = useSaveTenantSettings();
  const [form] = Form.useForm<FormValues>();
  const names = useNames(intlLocale);
  useTenantChannel((m) => {
    if (m.type === 'organization.settings_changed') void settings.refetch();
  });
  const saved = settings.data;
  useEffect(() => {
    if (saved !== undefined) form.setFieldsValue(saved);
  }, [saved, form]);

  if (!allowed) return <NoAccess titleKey="nav.admin_instance" />;
  if (saved === undefined) return null;

  const submit = (values: FormValues, confirmCurrency = false) => {
    // A cleared time zone is sent as null: not set, so people keep their browser's.
    const body: TenantSettingsInput = {
      ...values,
      time_zone: values.time_zone ?? null,
      confirm_currency: confirmCurrency,
    };
    save.mutate(
      { body, version: saved.version },
      {
        onSuccess: () => void message.success(t('instance.saved')),
        onError: (error) => {
          if (!showFieldErrors(form, error, t)) reportError(error);
        },
      },
    );
  };
  const onFinish = (values: FormValues) => {
    if (values.base_currency !== saved.base_currency && saved.version > 1) {
      modal.confirm({
        title: t('instance.currency_confirm', {
          from: names.currency(saved.base_currency),
          to: names.currency(values.base_currency),
        }),
        content: t('instance.currency_explain'),
        okText: t('instance.currency_change'),
        cancelText: t('actions.cancel'),
        onOk: () => {
          submit(values, true);
        },
      });
      return;
    }
    submit(values);
  };

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }} data-testid="instance">
      <PageHeader level={2} title={t('nav.admin_instance')} />
      <Typography.Paragraph type="secondary">{t('instance.intro')}</Typography.Paragraph>
      <Form<FormValues> form={form} layout="vertical" onFinish={onFinish} initialValues={saved}>
        <Card title={t('instance.defaults')}>
          <Flex gap={16} wrap>
            <Form.Item
              name="time_zone"
              label={t('instance.time_zone')}
              style={{ flex: '1 1 260px' }}
            >
              <Select
                showSearch
                allowClear
                placeholder={t('instance.time_zone_browser')}
                data-testid="instance-time-zone"
                options={names.zones.map((zone) => ({ value: zone, label: zone }))}
              />
            </Form.Item>
            <Form.Item
              name="week_start"
              label={t('instance.week_start')}
              style={{ flex: '1 1 180px' }}
            >
              <Select
                options={WEEK_STARTS.map((day) => ({
                  value: day,
                  label: t(`instance.week_start.${day}`),
                }))}
              />
            </Form.Item>
            <Form.Item
              name="date_format"
              label={t('instance.date_format')}
              style={{ flex: '1 1 180px' }}
            >
              <Select options={DATE_FORMATS.map((f) => ({ value: f, label: f }))} />
            </Form.Item>
            <Form.Item
              name="time_format"
              label={t('instance.time_format')}
              style={{ flex: '1 1 160px' }}
            >
              <Select
                options={TIME_FORMATS.map((f) => ({
                  value: f,
                  label: t(`instance.time_format.${f}`),
                }))}
              />
            </Form.Item>
            <Form.Item name="country" label={t('instance.country')} style={{ flex: '1 1 220px' }}>
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                options={COUNTRIES.map((code) => ({ value: code, label: names.region(code) }))}
              />
            </Form.Item>
            <Form.Item
              name="fiscal_year_start_month"
              label={t('instance.fiscal_year')}
              style={{ flex: '1 1 180px' }}
            >
              <Select
                options={Array.from({ length: 12 }, (_, i) => ({
                  value: i + 1,
                  label: names.month(i + 1),
                }))}
              />
            </Form.Item>
          </Flex>
        </Card>
        <Card title={t('instance.contact')} style={{ marginTop: 16 }}>
          <Flex gap={16} wrap>
            <Form.Item
              name="contact_email"
              label={t('instance.contact_email')}
              style={{ flex: '1 1 260px' }}
            >
              <Input type="email" dir="ltr" />
            </Form.Item>
            <Form.Item
              name="contact_phone"
              label={t('instance.contact_phone')}
              style={{ flex: '1 1 200px' }}
            >
              <Input dir="ltr" />
            </Form.Item>
          </Flex>
        </Card>
        <Card title={t('instance.money_languages')} style={{ marginTop: 16 }}>
          <Form.Item
            name="base_currency"
            label={t('instance.base_currency')}
            extra={t('instance.base_currency_help')}
          >
            <Select
              showSearch
              optionFilterProp="label"
              style={{ maxWidth: 360 }}
              data-testid="instance-currency"
              options={names.currencies.map((code) => ({
                value: code,
                label: names.currency(code),
              }))}
            />
          </Form.Item>
          <Form.Item
            name="languages"
            label={t('instance.languages')}
            extra={t('instance.languages_help')}
          >
            <Checkbox.Group
              data-testid="instance-languages"
              options={LANGUAGES.map((lang) => ({
                value: lang,
                label: t(`locale.${lang}`),
                disabled: lang === 'en',
              }))}
            />
          </Form.Item>
          <Form.Item name="default_language" label={t('instance.default_language')}>
            <Select
              style={{ maxWidth: 240 }}
              options={LANGUAGES.map((lang) => ({ value: lang, label: t(`locale.${lang}`) }))}
            />
          </Form.Item>
        </Card>
        <WriteButton
          type="primary"
          htmlType="submit"
          loading={save.isPending}
          style={{ marginTop: 16 }}
          data-testid="instance-save"
        >
          {t('actions.save')}
        </WriteButton>
      </Form>
    </Space>
  );
}
