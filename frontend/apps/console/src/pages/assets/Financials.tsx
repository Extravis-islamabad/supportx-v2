import {
  Alert,
  App,
  Card,
  Descriptions,
  Flex,
  Form,
  Input,
  InputNumber,
  Select,
  Skeleton,
  Statistic,
  Table,
} from 'antd';
import dayjs from 'dayjs';
import { useState } from 'react';

import {
  useAssetCostActions,
  useAssetFinancials,
  useAssetRecordChange,
  type AssetCost,
  type AssetCostKind,
  type AssetDepreciationChoice,
  type AssetDepreciationYear,
  type AssetFinancials,
  type AssetRecord,
  type AssetTermsSource,
} from '@supportx/api-client';
import {
  CellText,
  DateField,
  EditDialog,
  EmptyText,
  FormProblem,
  lengthLimit,
  RowActions,
  ToneTag,
  useDateTime,
  useFormProblem,
  useLabel,
  useLicence,
  WriteButton,
} from '@supportx/ui';

import { totalShown, useMoney } from './money';
import { problemText } from './problemText';

// No disposal kind: the disposal record carries the disposal cost (counted once).
const KINDS: AssetCostKind[] = ['service', 'move', 'contract', 'other'];
const METHODS: AssetDepreciationChoice[] = [
  'straight_line',
  'declining_balance',
  'double_declining_balance',
  'sum_of_years_digits',
  'none',
];
const DESCRIPTION_MAX = 500;

function Source({ from }: { from: AssetTermsSource | null }) {
  const t = useLabel();
  if (from === null) return null;
  return (
    <ToneTag tone={from === 'asset' ? 'info' : 'default'} testId={`asset-terms-from-${from}`}>
      {t(`asset_terms_source.${from}`)}
    </ToneTag>
  );
}

/** Configure depreciation (REQ-AST-037): the asset's own method, life and salvage value. */
function DepreciationDialog({
  asset,
  money,
  open,
  onClose,
}: {
  asset: AssetRecord;
  money: AssetFinancials;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const change = useAssetRecordChange();
  const own = money.depreciation;
  // Empty: the product's setting applies (REQ-AST-037 AC2).
  const [method, setMethod] = useState<AssetDepreciationChoice | null>(own.own_method);
  const [life, setLife] = useState<number | null>(own.own_useful_life_years);
  const [salvage, setSalvage] = useState<string | null>(own.own_salvage_value);
  const problem = useFormProblem();
  const dirty =
    method !== own.own_method ||
    life !== own.own_useful_life_years ||
    salvage !== own.own_salvage_value;
  return (
    <EditDialog
      open={open}
      title={t('assets.financials.configure')}
      okText={t('actions.save')}
      saving={change.isPending}
      dirty={dirty}
      onCancel={onClose}
      onOk={() => {
        problem.clear();
        change.mutate(
          {
            kind: 'update',
            id: asset.id,
            version: asset.version,
            body: {
              depreciation_method: method,
              useful_life_years: life,
              salvage_value: salvage,
            },
          },
          { onSuccess: onClose, onError: problem.show },
        );
      }}
      testId="asset-depreciation-dialog"
    >
      <Form layout="vertical">
        <FormProblem problem={problem} />
        <Form.Item label={t('assets.financials.method')} htmlFor="asset-depreciation-method">
          <Select<AssetDepreciationChoice>
            id="asset-depreciation-method"
            aria-label={t('assets.financials.method')}
            allowClear
            placeholder={t('assets.financials.from_product')}
            value={method ?? undefined}
            onChange={(value: AssetDepreciationChoice | undefined) => {
              setMethod(value ?? null);
            }}
            options={METHODS.map((code) => ({
              value: code,
              label: t(`asset_depreciation.${code}`),
            }))}
            data-testid="asset-depreciation-method"
          />
        </Form.Item>
        <Flex gap={16} wrap>
          <Form.Item label={t('assets.financials.life')} htmlFor="asset-depreciation-life">
            <InputNumber<number>
              id="asset-depreciation-life"
              min={1}
              max={100}
              precision={0}
              placeholder={t('assets.financials.from_product')}
              value={life}
              onChange={(value) => {
                setLife(value);
              }}
              style={{ width: 160 }}
              data-testid="asset-depreciation-life"
            />
          </Form.Item>
          <Form.Item label={t('assets.financials.salvage')} htmlFor="asset-depreciation-salvage">
            <InputNumber<string>
              id="asset-depreciation-salvage"
              stringMode
              min="0"
              step="0.01"
              precision={2}
              placeholder={t('assets.financials.from_product')}
              value={salvage}
              onChange={(value) => {
                setSalvage(value === '' ? null : value);
              }}
              style={{ width: 160 }}
              data-testid="asset-depreciation-salvage"
            />
          </Form.Item>
        </Flex>
      </Form>
    </EditDialog>
  );
}

/** Add or change a cost line (REQ-AST-036): kind, date, amount and what it was for. */
function CostDialog({
  assetId,
  editing,
  open,
  onClose,
}: {
  assetId: string;
  editing: AssetCost | null;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { create, update } = useAssetCostActions(assetId);
  const initial = {
    kind: editing?.kind ?? 'service',
    // A calendar day, no zone (the API's `incurred_on` is a date).
    on: editing?.incurred_on ?? dayjs().format('YYYY-MM-DD'),
    amount: editing?.amount ?? null,
    description: editing?.description ?? '',
  };
  const [kind, setKind] = useState<AssetCostKind>(initial.kind);
  const [on, setOn] = useState<string | null>(initial.on);
  const [amount, setAmount] = useState<string | null>(initial.amount);
  const [description, setDescription] = useState(initial.description);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const problem = useFormProblem();
  const pending = create.isPending || update.isPending;
  const dirty =
    kind !== initial.kind ||
    on !== initial.on ||
    amount !== initial.amount ||
    description !== initial.description;
  const failed = (error: unknown) => {
    setKey(crypto.randomUUID());
    problem.show(error);
  };
  return (
    <EditDialog
      open={open}
      title={t(editing === null ? 'assets.financials.add_cost' : 'assets.financials.edit_cost')}
      okText={t('actions.save')}
      saving={pending}
      okDisabled={amount === null || on === null}
      okWhyNot={
        amount === null
          ? t('assets.financials.amount_needed')
          : on === null
            ? t('assets.financials.date_needed')
            : undefined
      }
      dirty={dirty}
      onCancel={onClose}
      onOk={() => {
        if (amount === null || on === null) return;
        problem.clear();
        const body = {
          kind,
          incurred_on: on,
          amount,
          description: description.trim() === '' ? null : description.trim(),
        };
        if (editing === null) {
          create.mutate({ key, body }, { onSuccess: onClose, onError: failed });
        } else {
          update.mutate(
            { id: editing.id, version: editing.version, body },
            { onSuccess: onClose, onError: failed },
          );
        }
      }}
      testId="asset-cost-dialog"
    >
      <Form layout="vertical">
        <FormProblem problem={problem} />
        <Flex gap={16} wrap>
          <Form.Item label={t('assets.financials.kind')} htmlFor="asset-cost-kind">
            <Select<AssetCostKind>
              id="asset-cost-kind"
              aria-label={t('assets.financials.kind')}
              value={kind}
              onChange={setKind}
              options={KINDS.map((code) => ({ value: code, label: t(`asset_cost_kind.${code}`) }))}
              style={{ minWidth: 160 }}
              data-testid="asset-cost-kind"
            />
          </Form.Item>
          <Form.Item label={t('assets.financials.date')} htmlFor="asset-cost-date" required>
            <DateField
              id="asset-cost-date"
              value={on}
              onChange={setOn}
              ariaLabel={t('assets.financials.date')}
              testId="asset-cost-date"
            />
          </Form.Item>
          <Form.Item label={t('assets.financials.amount')} htmlFor="asset-cost-amount" required>
            <InputNumber<string>
              id="asset-cost-amount"
              stringMode
              min="0"
              step="0.01"
              precision={2}
              value={amount}
              onChange={(value) => {
                setAmount(value === '' ? null : value);
              }}
              style={{ width: 160 }}
              data-testid="asset-cost-amount"
            />
          </Form.Item>
        </Flex>
        <Form.Item label={t('assets.financials.description')} htmlFor="asset-cost-description">
          <Input
            id="asset-cost-description"
            dir="auto"
            count={lengthLimit(DESCRIPTION_MAX)}
            value={description}
            onChange={(event) => {
              setDescription(event.target.value);
            }}
            data-testid="asset-cost-description"
          />
        </Form.Item>
      </Form>
    </EditDialog>
  );
}

/**
 * The asset's Financials tab (WP-049b s2; REQ-AST-036..038): purchase, book value, operational
 * cost and total cost of ownership; the depreciation in effect with where each setting came
 * from, and its schedule by year; the cost lines. Shown only to people with
 * `assets.view_financials` (the page leaves the tab out otherwise; the API refuses anyway).
 * Live: the asset's channel names "costs" or a change of the asset, and this refetches.
 */
export function AssetFinancialsTab({ asset, manage }: { asset: AssetRecord; manage: boolean }) {
  const t = useLabel();
  const dates = useDateTime();
  const found = useAssetFinancials(asset.id);
  const { remove } = useAssetCostActions(asset.id);
  const { modal } = App.useApp();
  const { writable } = useLicence();
  // Read-only mode: the row's actions stay, disabled, saying why (D-155).
  const readOnly = writable ? undefined : t('licence.read_only_action');
  const [dialog, setDialog] = useState<'depreciation' | 'cost'>();
  const [editing, setEditing] = useState<AssetCost | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const money = useMoney(found.data?.currency);
  const confirmDelete = (cost: AssetCost) => {
    modal.confirm({
      title: t('assets.financials.delete_confirm'),
      okText: t('actions.delete'),
      okButtonProps: { danger: true, 'data-testid': 'asset-cost-delete-confirm' },
      cancelText: t('actions.cancel'),
      onOk: () => {
        setProblem(null);
        remove.mutate(
          { id: cost.id, version: cost.version },
          {
            onError: (error) => {
              setProblem(problemText(t, error));
            },
          },
        );
      },
    });
  };
  if (found.data === undefined) return <Skeleton active />;
  const data = found.data;
  const shown = (amount: string | null) => money(amount) ?? t('assets.financials.not_known');
  const terms = data.depreciation;
  const cards: { key: string; label: string; text: string }[] = [
    { key: 'purchase', label: t('assets.financials.purchase'), text: shown(data.purchase) },
    { key: 'book-value', label: t('assets.financials.book_value'), text: shown(data.book_value) },
    {
      key: 'operational',
      label: t('assets.financials.operational'),
      text: shown(data.operational),
    },
    {
      key: 'total',
      label: t('assets.financials.total_cost'),
      text: totalShown(money, data),
    },
  ];
  return (
    <Flex vertical gap={16} style={{ paddingBottom: 16 }} data-testid="asset-financials">
      {data.currency_differs && (
        <Alert
          type="warning"
          showIcon
          message={t('assets.financials.currency_differs', {
            currency: data.purchase_currency ?? '',
            base: data.currency,
          })}
          data-testid="asset-financials-currency"
        />
      )}
      <Flex gap={12} wrap>
        {cards.map((card) => (
          <Card key={card.key} size="small" style={{ flex: '1 1 160px', minWidth: 0 }}>
            <Statistic
              title={card.label}
              value={card.text}
              formatter={() => <span data-testid={`asset-fin-${card.key}`}>{card.text}</span>}
              valueStyle={{ fontSize: 20 }}
            />
          </Card>
        ))}
      </Flex>
      <Card
        size="small"
        title={t('assets.financials.depreciation')}
        extra={
          manage && (
            <WriteButton
              size="small"
              onClick={() => {
                setDialog('depreciation');
              }}
              data-testid="asset-depreciation-open"
            >
              {t('assets.financials.configure')}
            </WriteButton>
          )
        }
      >
        <Descriptions
          size="small"
          column={{ xs: 1, md: 2 }}
          items={[
            {
              key: 'method',
              label: t('assets.financials.method'),
              children: (
                <Flex gap={6} wrap align="center" data-testid="asset-depreciation-method-shown">
                  {terms.method === null
                    ? t('assets.financials.method_not_set')
                    : t(`asset_depreciation.${terms.method}`)}
                  <Source from={terms.method_from} />
                </Flex>
              ),
            },
            {
              key: 'life',
              label: t('assets.financials.life'),
              children: (
                <Flex gap={6} wrap align="center">
                  {terms.useful_life_years === null
                    ? t('assets.financials.not_known')
                    : t('assets.financials.life_years', { count: terms.useful_life_years })}
                  <Source from={terms.life_from} />
                </Flex>
              ),
            },
            {
              key: 'salvage',
              label: t('assets.financials.salvage'),
              children: (
                <Flex gap={6} wrap align="center">
                  {shown(terms.salvage_value)}
                  <Source from={terms.salvage_from} />
                </Flex>
              ),
            },
            {
              key: 'starts',
              label: t('assets.financials.starts_on'),
              children:
                terms.starts_on === null
                  ? t('assets.financials.not_known')
                  : dates.formatDay(terms.starts_on),
            },
          ]}
        />
        <Table<AssetDepreciationYear>
          size="small"
          rowKey="year"
          pagination={false}
          scroll={{ x: 'max-content' }}
          dataSource={terms.schedule}
          locale={{ emptyText: <EmptyText>{t('assets.financials.schedule_none')}</EmptyText> }}
          columns={[
            {
              key: 'year',
              title: t('assets.financials.year'),
              render: (_, y) => t('assets.financials.year_n', { n: y.year }),
            },
            {
              key: 'from',
              title: t('assets.financials.year_starts'),
              render: (_, y) => dates.formatDay(y.starts_on),
            },
            {
              key: 'opening',
              title: t('assets.financials.opening'),
              render: (_, y) => money(y.opening),
            },
            {
              key: 'depreciation',
              title: t('assets.financials.depreciation_amount'),
              render: (_, y) => money(y.depreciation),
            },
            {
              key: 'closing',
              title: t('assets.financials.closing'),
              render: (_, y) => money(y.closing),
            },
          ]}
          data-testid="asset-depreciation-schedule"
        />
      </Card>
      <Card
        size="small"
        title={t('assets.financials.costs')}
        extra={
          manage && (
            <WriteButton
              size="small"
              onClick={() => {
                setEditing(null);
                setDialog('cost');
              }}
              data-testid="asset-cost-add"
            >
              {t('assets.financials.add_cost')}
            </WriteButton>
          )
        }
      >
        {problem !== null && (
          <Alert
            type="error"
            showIcon
            closable
            message={problem}
            onClose={() => {
              setProblem(null);
            }}
            style={{ marginBottom: 12 }}
          />
        )}
        <Table<AssetCost>
          size="small"
          rowKey="id"
          pagination={false}
          scroll={{ x: 'max-content' }}
          dataSource={data.costs}
          locale={{ emptyText: <EmptyText>{t('assets.financials.no_costs')}</EmptyText> }}
          columns={[
            {
              key: 'date',
              title: t('assets.financials.date'),
              render: (_, c) => (
                <span style={{ whiteSpace: 'nowrap' }}>{dates.formatDay(c.incurred_on)}</span>
              ),
            },
            {
              key: 'kind',
              title: t('assets.financials.kind'),
              render: (_, c) => t(`asset_cost_kind.${c.kind}`),
            },
            {
              key: 'amount',
              title: t('assets.financials.amount'),
              render: (_, c) => money(c.amount),
            },
            {
              key: 'description',
              title: t('assets.financials.description'),
              render: (_, c) => (
                <CellText>
                  {c.description === null ? '' : <bdi dir="auto">{c.description}</bdi>}
                </CellText>
              ),
            },
            ...(manage
              ? [
                  {
                    key: 'actions',
                    // Named for screen readers only, as the other row-action tables do.
                    title: <span className="sr-only">{t('assets.financials.actions')}</span>,
                    fixed: 'right' as const,
                    render: (_: unknown, c: AssetCost) => (
                      <RowActions
                        rowName={t('assets.financials.cost_row', {
                          kind: t(`asset_cost_kind.${c.kind}`),
                          date: dates.formatDay(c.incurred_on),
                        })}
                        primary={{
                          key: 'edit',
                          label: t('actions.edit'),
                          disabled: !writable,
                          whyNot: readOnly,
                          onClick: () => {
                            setEditing(c);
                            setDialog('cost');
                          },
                          testId: `asset-cost-edit-${c.id}`,
                        }}
                        more={[
                          {
                            key: 'delete',
                            label: t('actions.delete'),
                            danger: true,
                            disabled: !writable,
                            whyNot: readOnly,
                            onClick: () => {
                              confirmDelete(c);
                            },
                            testId: `asset-cost-delete-${c.id}`,
                          },
                        ]}
                      />
                    ),
                  },
                ]
              : []),
          ]}
          data-testid="asset-costs-table"
        />
      </Card>
      {dialog === 'depreciation' && (
        <DepreciationDialog
          asset={asset}
          money={data}
          open
          onClose={() => {
            setDialog(undefined);
          }}
        />
      )}
      {dialog === 'cost' && (
        <CostDialog
          assetId={asset.id}
          editing={editing}
          open
          onClose={() => {
            setDialog(undefined);
            setEditing(null);
          }}
        />
      )}
    </Flex>
  );
}
