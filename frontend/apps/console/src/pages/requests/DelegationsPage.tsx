import { useQueryClient } from '@tanstack/react-query';
import { DatePicker, Flex, Form, Input, Table, Typography } from 'antd';
import type { Dayjs } from 'dayjs';
import { useState } from 'react';

import {
  delegationKeys,
  useCreateDelegation,
  useDelegations,
  useEndDelegation,
  type Delegation,
} from '@supportx/api-client';
import {
  lengthLimit,
  PageHeader,
  reportError,
  SettingsCard,
  ToneTag,
  useAccess,
  useDateTime,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { refreshQueries, usePersonalChannel } from '@supportx/realtime';

import { PersonName } from '../admin/erasures/words';
import { UserPicker } from '../incidents/pickers';

const MAX_DAYS = 90; // as the server's (the coordinator's condition 1)
const DELEGATIONS_CHANGED = 'work_items.delegations_changed';
const REASON_MAX = 500;
type State = 'active' | 'upcoming' | 'ended';

function stateOf(d: Delegation, now: number): State {
  const until = Math.min(Date.parse(d.ends_at), d.ended_at ? Date.parse(d.ended_at) : Infinity);
  if (until <= now) return 'ended';
  return Date.parse(d.starts_at) > now ? 'upcoming' : 'active';
}

const TONE = { active: 'success', upcoming: 'info', ended: 'info' } as const;

/**
 * Approval delegations (WP-047a S3b; REQ-SR-035): while one is active, new request approvals
 * for the approver go to the delegate, and the approver can still decide them. Your own, and with
 * `requests.manage_delegations` someone else's. Ending one sends what is still pending back.
 */
export function DelegationsPage() {
  const t = useLabel();
  const { format } = useDateTime();
  const { can } = useAccess();
  const manages = can('requests.manage_delegations');
  const list = useDelegations();
  const queryClient = useQueryClient();
  // Live (rule 5c; lane C's #612 review): a change by the other person, an administrator or
  // the sweep's expiry arrives on your own channel as IDs only, and the list refetches.
  usePersonalChannel((message) => {
    if (message.type === DELEGATIONS_CHANGED || message.type === 'refresh') {
      refreshQueries(queryClient, delegationKeys.all);
    }
  });
  const create = useCreateDelegation();
  const end = useEndDelegation();
  const [delegator, setDelegator] = useState<string | null>(null);
  const [delegate, setDelegate] = useState<string | null>(null);
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [reason, setReason] = useState('');
  const [formKey, setFormKey] = useState(() => crypto.randomUUID());
  const tooLong = range !== null && range[1].diff(range[0], 'day', true) > MAX_DAYS;
  const ready = delegate !== null && range !== null && !tooLong;
  // Read once per mount: a delegation's state moves on with the list's next refetch.
  const [now] = useState(() => Date.now());
  return (
    <Flex vertical gap={16} style={{ maxWidth: 960 }}>
      <PageHeader title={t('delegations.title')} />
      <SettingsCard title={t('delegations.new')}>
        <Form layout="vertical" component="div">
          {manages && (
            <Form.Item label={t('delegations.delegator')} extra={t('delegations.delegator_help')}>
              <UserPicker
                value={delegator}
                onChange={setDelegator}
                testId="delegation-delegator"
                ariaLabel={t('delegations.delegator')}
              />
            </Form.Item>
          )}
          <Form.Item label={t('delegations.delegate')} required>
            <UserPicker
              value={delegate}
              onChange={setDelegate}
              testId="delegation-delegate"
              ariaLabel={t('delegations.delegate')}
            />
          </Form.Item>
          <Form.Item
            label={t('delegations.dates')}
            required
            validateStatus={tooLong ? 'error' : undefined}
            help={tooLong ? t('errors.field.delegation_too_long') : t('delegations.dates_help')}
          >
            <DatePicker.RangePicker
              showTime
              value={range}
              onChange={(value) => {
                setRange(value?.[0] && value[1] ? [value[0], value[1]] : null);
              }}
              aria-label={t('delegations.dates')}
              data-testid="delegation-dates"
            />
          </Form.Item>
          <Form.Item label={t('delegations.reason')}>
            <Input
              value={reason}
              count={lengthLimit(REASON_MAX)}
              onChange={(e) => {
                setReason(e.target.value);
              }}
              data-testid="delegation-reason"
            />
          </Form.Item>
          <WriteButton
            type="primary"
            disabled={!ready}
            whyDisabled={t('why.delegation_needs_delegate_and_dates')}
            loading={create.isPending}
            onClick={() => {
              if (!ready) return;
              create.mutate(
                {
                  key: formKey,
                  body: {
                    delegator_id: delegator,
                    delegate_id: delegate,
                    starts_at: range[0].toISOString(),
                    ends_at: range[1].toISOString(),
                    reason: reason.trim() === '' ? null : reason.trim(),
                  },
                },
                {
                  onSuccess: () => {
                    setDelegate(null);
                    setRange(null);
                    setReason('');
                    setFormKey(crypto.randomUUID());
                  },
                  onError: reportError,
                },
              );
            }}
            data-testid="delegation-save"
          >
            {t('delegations.save')}
          </WriteButton>
        </Form>
      </SettingsCard>
      <Table<Delegation>
        rowKey="id"
        loading={list.isLoading}
        dataSource={list.data?.items ?? []}
        pagination={false}
        data-testid="delegations"
        locale={{ emptyText: t('delegations.none') }}
        columns={[
          {
            title: t('delegations.delegator'),
            render: (_, d) => <PersonName id={d.delegator_id} />,
          },
          {
            title: t('delegations.delegate'),
            render: (_, d) => <PersonName id={d.delegate_id} />,
          },
          {
            title: t('delegations.dates'),
            render: (_, d) => (
              <Typography.Text>
                {format(d.starts_at)} – {format(d.ended_at ?? d.ends_at)}
              </Typography.Text>
            ),
          },
          {
            title: t('delegations.state'),
            render: (_, d) => {
              const state = stateOf(d, now);
              return (
                <ToneTag tone={TONE[state]} testId="delegation-state">
                  {t(`delegation_state.${state}`)}
                </ToneTag>
              );
            },
          },
          {
            title: '',
            render: (_, d) =>
              stateOf(d, now) === 'ended' ? null : (
                <WriteButton
                  size="small"
                  onClick={() => {
                    end.mutate({ id: d.id, version: d.version }, { onError: reportError });
                  }}
                  data-testid="delegation-end"
                >
                  {t('delegations.end')}
                </WriteButton>
              ),
          },
        ]}
      />
    </Flex>
  );
}
