import { Button, Flex, Select, Table, Typography } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  queryKeys,
  useSignIns,
  type SignInEvent,
  type SignInFilters,
  type SignInMethod,
  type SignInOutcome,
} from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import { ToneTag, useDateTime, useLabel, type Tone } from '@supportx/ui';

const OUTCOMES: SignInOutcome[] = ['success', 'failed', 'signed_out', 'locked', 'mfa_failed'];
const METHODS: SignInMethod[] = [
  'password',
  'single_sign_on',
  'directory',
  'mobile',
  'api_key',
  'unknown',
];
const PERIODS = ['day', 'week', 'month', 'all'] as const;
type Period = (typeof PERIODS)[number];
const PERIOD_HOURS: Record<Period, number | null> = { day: 24, week: 168, month: 720, all: null };
const TONES: Record<SignInOutcome, Tone> = {
  success: 'success',
  failed: 'error',
  signed_out: 'default',
  locked: 'error',
  mfa_failed: 'warning',
};
const PAGE = 50;
const MAX_SHOWN = 200; // the server's page cap; past it the filters narrow the list

/** The start of a period from now, as an instant (undefined: everything kept). */
function sinceFor(period: Period): string | undefined {
  const hours = PERIOD_HOURS[period];
  return hours === null ? undefined : new Date(Date.now() - hours * 3600_000).toISOString();
}

/** "chrome:windows" as words ("Chrome on Windows"); an unknown part as "Other". */
function deviceText(t: ReturnType<typeof useLabel>, device: string | null): string {
  if (device === null) return t('sign_in_device.unknown');
  const [browser = 'other', system = 'other'] = device.split(':');
  return t('sign_in_device.on', {
    browser: t(`sign_in_device.browser.${browser}`),
    system: t(`sign_in_device.system.${system}`),
  });
}

/**
 * Audit › Sign-ins (WP-057 S1a, REQ-AUD-015): every sign-in, refusal and sign-out of the
 * organisation, newest first, live. Filters by outcome, method and period (AC2: "failed" in the
 * last 24 hours lists only those). Each read is audited server-side (a personal-data read).
 */
export function SignInsTab() {
  const t = useLabel();
  const dates = useDateTime();
  const queryClient = useQueryClient();
  const [outcomes, setOutcomes] = useState<SignInOutcome[]>([]);
  const [methods, setMethods] = useState<SignInMethod[]>([]);
  const [period, setPeriod] = useState<Period>('week');
  const [shown, setShown] = useState(PAGE);
  // The period's start, fixed when it is chosen: a moving "now" would refetch on every render.
  const [since, setSince] = useState<string | undefined>(() => sinceFor('week'));
  const filters: SignInFilters = {
    ...(outcomes.length > 0 ? { outcome: outcomes } : {}),
    ...(methods.length > 0 ? { method: methods } : {}),
    ...(since !== undefined ? { since } : {}),
    limit: shown,
  };
  const page = useSignIns(filters);
  useListChannel('sign_ins', () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.identity.signInsAll });
  });
  const rows = page.data?.items ?? [];
  const people = page.data?.people ?? {};
  const more = (page.data?.next_cursor ?? null) !== null;
  const reset = () => {
    setShown(PAGE);
  };
  return (
    <Flex vertical gap={12} data-testid="audit-sign-ins">
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        {t('audit.sign_ins.intro')}
      </Typography.Paragraph>
      <Flex gap={8} wrap>
        <Select<SignInOutcome[]>
          mode="multiple"
          allowClear
          style={{ minWidth: 200 }}
          placeholder={t('audit.sign_ins.any_outcome')}
          aria-label={t('audit.sign_ins.outcome')}
          value={outcomes}
          onChange={(value) => {
            setOutcomes(value);
            reset();
          }}
          options={OUTCOMES.map((o) => ({ value: o, label: t(`sign_in_outcome.${o}`) }))}
          data-testid="sign-ins-outcome"
        />
        <Select<SignInMethod[]>
          mode="multiple"
          allowClear
          style={{ minWidth: 200 }}
          placeholder={t('audit.sign_ins.any_method')}
          aria-label={t('audit.sign_ins.method')}
          value={methods}
          onChange={(value) => {
            setMethods(value);
            reset();
          }}
          options={METHODS.map((m) => ({ value: m, label: t(`sign_in_method.${m}`) }))}
          data-testid="sign-ins-method"
        />
        <Select<Period>
          style={{ minWidth: 180 }}
          aria-label={t('audit.sign_ins.period')}
          value={period}
          onChange={(value) => {
            setPeriod(value);
            setSince(sinceFor(value));
            reset();
          }}
          options={PERIODS.map((p) => ({ value: p, label: t(`audit.sign_ins.period.${p}`) }))}
          data-testid="sign-ins-period"
        />
      </Flex>
      <Table<SignInEvent>
        rowKey="id"
        size="small"
        loading={page.isLoading}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 960 }}
        locale={{ emptyText: t('audit.sign_ins.empty') }}
        columns={[
          {
            key: 'when',
            title: t('audit.sign_ins.when'),
            width: 170,
            render: (_, row) => dates.format(row.occurred_at),
          },
          {
            key: 'person',
            title: t('audit.sign_ins.person'),
            width: 200,
            render: (_, row) => {
              const person = row.user_id === null ? undefined : people[row.user_id];
              return person === undefined ? (
                <Typography.Text type="secondary">
                  {t('audit.sign_ins.unknown_person')}
                </Typography.Text>
              ) : (
                <bdi dir="auto">{person.display_name}</bdi>
              );
            },
          },
          {
            key: 'outcome',
            title: t('audit.sign_ins.outcome'),
            width: 130,
            render: (_, row) => (
              <ToneTag tone={TONES[row.outcome]}>{t(`sign_in_outcome.${row.outcome}`)}</ToneTag>
            ),
          },
          {
            key: 'reason',
            title: t('audit.sign_ins.reason'),
            width: 220,
            render: (_, row) => (row.reason === null ? '' : t(`sign_in_reason.${row.reason}`)),
          },
          {
            key: 'method',
            title: t('audit.sign_ins.method'),
            width: 140,
            render: (_, row) => t(`sign_in_method.${row.method}`),
          },
          {
            key: 'app',
            title: t('audit.sign_ins.app'),
            width: 110,
            render: (_, row) => t(`sign_in_app.${row.app}`),
          },
          {
            key: 'address',
            title: t('audit.sign_ins.address'),
            width: 150,
            render: (_, row) => <bdi dir="ltr">{row.ip ?? ''}</bdi>,
          },
          {
            key: 'device',
            title: t('audit.sign_ins.device'),
            width: 180,
            render: (_, row) => deviceText(t, row.device),
          },
        ]}
        data-testid="sign-ins-table"
      />
      {more && shown < MAX_SHOWN && (
        <div>
          <Button
            onClick={() => {
              setShown(Math.min(shown + PAGE, MAX_SHOWN));
            }}
            data-testid="sign-ins-more"
          >
            {t('audit.sign_ins.more')}
          </Button>
        </div>
      )}
      {more && shown >= MAX_SHOWN && (
        <Typography.Text type="secondary">{t('audit.sign_ins.narrow')}</Typography.Text>
      )}
    </Flex>
  );
}
