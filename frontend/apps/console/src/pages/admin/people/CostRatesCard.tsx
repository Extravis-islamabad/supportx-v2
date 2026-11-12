import { App, Card, Flex, Form, InputNumber, Skeleton, Table, Typography } from 'antd';
import { useState } from 'react';

import {
  useCostRateActions,
  useCostRates,
  type CostRate,
  type CostRateState,
} from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import {
  DateTimeField,
  EditDialog,
  EmptyText,
  FormProblem,
  RowActions,
  ToneTag,
  WriteButton,
  useAccess,
  useAppearance,
  useDateTime,
  useFormProblem,
  useLabel,
  useLicence,
} from '@supportx/ui';

import { problemText } from '../../assets/problemText';

export const VIEW_COST_RATES = 'users.view_cost_rates';
export const MANAGE_COST_RATES = 'users.manage_cost_rates';

const TONES: Record<CostRateState, 'success' | 'info' | 'default'> = {
  current: 'success',
  future: 'info',
  past: 'default',
};

/** Set a new rate, or change the current or an upcoming one: the amount and its start. */
function RateDialog({
  userId,
  currency,
  editing,
  onClose,
}: {
  userId: string;
  currency: string;
  editing: CostRate | null;
  onClose: () => void;
}) {
  const t = useLabel();
  const { create, update } = useCostRateActions(userId);
  const initial = {
    rate: editing?.rate ?? null,
    from: editing?.effective_from ?? new Date().toISOString(),
  };
  const [rate, setRate] = useState<string | null>(initial.rate);
  const [from, setFrom] = useState<string | null>(initial.from);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const problem = useFormProblem();
  const failed = (error: unknown) => {
    setKey(crypto.randomUUID());
    problem.show(error);
  };
  const missing = rate === null || from === null;
  return (
    <EditDialog
      open
      title={t(editing === null ? 'people.cost_rate.add' : 'people.cost_rate.change')}
      okText={t('actions.save')}
      saving={create.isPending || update.isPending}
      okDisabled={missing}
      okWhyNot={
        rate === null
          ? t('people.cost_rate.rate')
          : from === null
            ? t('people.cost_rate.effective_from')
            : undefined
      }
      dirty={rate !== initial.rate || from !== initial.from}
      onCancel={onClose}
      onOk={() => {
        if (rate === null || from === null) return;
        problem.clear();
        if (editing === null) {
          create.mutate(
            { key, body: { rate, effective_from: from } },
            { onSuccess: onClose, onError: failed },
          );
        } else {
          update.mutate(
            { id: editing.id, version: editing.version, body: { rate, effective_from: from } },
            { onSuccess: onClose, onError: failed },
          );
        }
      }}
      testId="cost-rate-dialog"
    >
      <Form layout="vertical">
        <FormProblem problem={problem} />
        <Flex gap={16} wrap>
          <Form.Item
            label={`${t('people.cost_rate.rate')} (${currency})`}
            htmlFor="cost-rate-amount"
            required
          >
            <InputNumber<string>
              id="cost-rate-amount"
              stringMode
              min="0"
              step="0.01"
              precision={2}
              value={rate}
              onChange={(value) => {
                setRate(value === '' ? null : value);
              }}
              style={{ width: 160 }}
              data-testid="cost-rate-amount"
            />
          </Form.Item>
          <Form.Item label={t('people.cost_rate.effective_from')} htmlFor="cost-rate-from" required>
            <DateTimeField
              id="cost-rate-from"
              value={from}
              onChange={setFrom}
              testId="cost-rate-from"
            />
          </Form.Item>
        </Flex>
      </Form>
    </EditDialog>
  );
}

/**
 * A person's cost per hour (REQ-INC-068): the rate in force now, every rate with its start, and
 * set-new-rate. Shown only to people with `users.view_cost_rates` (the drawer leaves it out
 * otherwise; the API refuses anyway); changes need `users.manage_cost_rates`. A superseded rate
 * stays as it was: the correction is a new rate. Live: the rates refetch when anyone changes
 * this person's rates (the channel names the person, never an amount).
 */
export function CostRatesCard({ userId }: { userId: string }) {
  const t = useLabel();
  const { can } = useAccess();
  const { writable } = useLicence();
  const { modal } = App.useApp();
  const dates = useDateTime();
  const visible = can(VIEW_COST_RATES);
  const manage = visible && can(MANAGE_COST_RATES);
  const rates = useCostRates(userId, visible);
  const { remove } = useCostRateActions(userId);
  const [dialog, setDialog] = useState<{ editing: CostRate | null } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const { intlLocale } = useAppearance();
  // Each rate in its own currency (the base currency when it was set); exact strings from the
  // API, a double only for display (NUMERIC(12, 2) fits one exactly to the cent).
  const rateMoney = (rate: CostRate) =>
    new Intl.NumberFormat(intlLocale, { style: 'currency', currency: rate.currency }).format(
      Number(rate.rate),
    );
  useListChannel(visible ? 'user_cost_rates' : null, (message) => {
    if (message.ids.length === 0 || message.ids.includes(userId)) void rates.refetch();
  });
  if (!visible) return null;
  const data = rates.data;
  const readOnly = writable ? undefined : t('licence.read_only_action');
  const confirmRemove = (rate: CostRate) => {
    modal.confirm({
      title: t('people.cost_rate.remove_confirm'),
      okText: t('people.cost_rate.remove'),
      okButtonProps: { danger: true, 'data-testid': 'cost-rate-remove-confirm' },
      cancelText: t('actions.cancel'),
      onOk: () => {
        setProblem(null);
        remove.mutate(
          { id: rate.id, version: rate.version },
          {
            onError: (error) => {
              setProblem(problemText(t, error));
            },
          },
        );
      },
    });
  };
  return (
    <Card
      title={t('people.cost_rate.title')}
      size="small"
      data-testid="cost-rates-card"
      extra={
        manage && (
          <WriteButton
            size="small"
            onClick={() => {
              setDialog({ editing: null });
            }}
            data-testid="cost-rate-add"
          >
            {t('people.cost_rate.add')}
          </WriteButton>
        )
      }
    >
      <Typography.Paragraph type="secondary">{t('people.cost_rate.help')}</Typography.Paragraph>
      {problem !== null && (
        <Typography.Paragraph type="danger" role="alert" data-testid="cost-rate-problem">
          {problem}
        </Typography.Paragraph>
      )}
      {data === undefined ? (
        <Skeleton active paragraph={{ rows: 2 }} />
      ) : (
        <>
          <Flex gap={8} align="baseline" data-testid="cost-rate-current">
            <Typography.Text type="secondary">{t('people.cost_rate.current')}</Typography.Text>
            {data.current === null ? (
              <EmptyText>
                {t(data.items.length === 0 ? 'people.cost_rate.none' : 'people.cost_rate.not_yet')}
              </EmptyText>
            ) : (
              <Typography.Text strong>
                <bdi>{rateMoney(data.current)}</bdi>
              </Typography.Text>
            )}
          </Flex>
          {data.items.length > 0 && (
            <Table<CostRate>
              size="small"
              rowKey="id"
              pagination={false}
              style={{ marginTop: 12 }}
              caption={<span className="sr-only">{t('people.cost_rate.history')}</span>}
              dataSource={data.items}
              columns={[
                {
                  key: 'rate',
                  title: t('people.cost_rate.rate'),
                  render: (_, r) => <bdi>{rateMoney(r)}</bdi>,
                },
                {
                  key: 'from',
                  title: t('people.cost_rate.effective_from'),
                  render: (_, r) => dates.format(r.effective_from),
                },
                {
                  key: 'state',
                  title: <span className="sr-only">{t('people.cost_rate.history')}</span>,
                  render: (_, r) => (
                    <ToneTag tone={TONES[r.state]} testId={`cost-rate-state-${r.id}`}>
                      {t(`people.cost_rate.state.${r.state}`)}
                    </ToneTag>
                  ),
                },
                ...(manage
                  ? [
                      {
                        key: 'actions',
                        title: <span className="sr-only">{t('people.cost_rate.history')}</span>,
                        render: (_: unknown, r: CostRate) => (
                          <RowActions
                            rowName={t('people.cost_rate.from_value', {
                              date: dates.format(r.effective_from),
                            })}
                            primary={
                              r.state === 'past'
                                ? undefined
                                : {
                                    key: 'change',
                                    label: t('people.cost_rate.change'),
                                    disabled: !writable,
                                    whyNot: readOnly,
                                    onClick: () => {
                                      setDialog({ editing: r });
                                    },
                                    testId: `cost-rate-change-${r.id}`,
                                  }
                            }
                            more={[
                              {
                                key: 'remove',
                                label: t('people.cost_rate.remove'),
                                danger: true,
                                disabled: !writable,
                                whyNot: readOnly,
                                onClick: () => {
                                  confirmRemove(r);
                                },
                                testId: `cost-rate-remove-${r.id}`,
                              },
                            ]}
                          />
                        ),
                      },
                    ]
                  : []),
              ]}
              data-testid="cost-rates-table"
            />
          )}
        </>
      )}
      {dialog !== null && data !== undefined && (
        <RateDialog
          userId={userId}
          currency={data.currency}
          editing={dialog.editing}
          onClose={() => {
            setDialog(null);
          }}
        />
      )}
    </Card>
  );
}
