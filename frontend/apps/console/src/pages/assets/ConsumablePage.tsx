import { InboxOutlined } from '@ant-design/icons';
import {
  Alert,
  DatePicker,
  Flex,
  Form,
  Input,
  InputNumber,
  Modal,
  Segmented,
  Select,
  Skeleton,
  Table,
  Typography,
} from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';

import {
  useConsumable,
  useConsumableActions,
  useConsumableLedger,
  useTenantSettings,
  useUser,
  type AssetBatch,
  type AssetConsumableDetail,
  type AssetMovement,
  type AssetRecipientKind,
  type AssetStock,
} from '@supportx/api-client';
import {
  ActionBar,
  CellText,
  EmptyText,
  lengthLimit,
  loadedEmpty,
  NoAccess,
  PropertiesPanel,
  PropertyList,
  RecordHeader,
  RecordPage,
  ToneTag,
  useAccess,
  useDateTime,
  useLabel,
  usePageCrumbs,
  type RecordAction,
  Tabs,
} from '@supportx/ui';

import { DepartmentPicker, SitePicker, UserPicker } from '../incidents/pickers';
import { AssetPicker, DepartmentName } from './AssetRelations';
import { useConsumablesLive, useSiteNames } from './live';
import { okFooter } from './dialogOk';
import { problemText } from './problemText';
import { plainQuantity, stockLevelKey, unsignedQuantity } from './quantity';
import { useMoney } from './money';

const COMMENT_MAX = 2000;
const RECIPIENTS: AssetRecipientKind[] = ['user', 'department', 'asset'];
export type StockMode = 'receive' | 'allocate' | 'adjust' | 'return';

function PersonName({ id }: { id: string }) {
  const t = useLabel();
  const user = useUser(id);
  return <bdi dir="auto">{user.data?.display_name ?? t('audit.ui.erased_person')}</bdi>;
}

/** Who an allocation went to, or a return came from: by name, never an ID. */
function Recipient({ row }: { row: AssetMovement }) {
  const t = useLabel();
  if (row.recipient_id === null || row.recipient_kind === null) return null;
  if (row.recipient_kind === 'user') return <PersonName id={row.recipient_id} />;
  if (row.recipient_kind === 'department') return <DepartmentName id={row.recipient_id} />;
  return <Link to={`/assets/${row.recipient_id}`}>{t('assets.stock.an_asset')}</Link>;
}

interface Draft {
  stockId: string | null;
  siteId: string | null;
  quantity: string | null;
  recipientKind: AssetRecipientKind;
  recipientId: string | null;
  batchId: string | null;
  lot: string;
  reference: string;
  made: Dayjs | null;
  expires: Dayjs | null;
  location: string;
  cost: string | null;
  day: Dayjs | null;
  comment: string;
}

const EMPTY: Draft = {
  stockId: null,
  siteId: null,
  quantity: null,
  recipientKind: 'user',
  recipientId: null,
  batchId: null,
  lot: '',
  reference: '',
  made: null,
  expires: null,
  location: '',
  cost: null,
  day: null,
  comment: '',
};

const iso = (day: Dayjs | null) => (day === null ? null : day.format('YYYY-MM-DD'));

/** Why the dialog's button cannot be used yet, or undefined. */
function whyNot(t: ReturnType<typeof useLabel>, mode: StockMode, d: Draft, batches: boolean) {
  if (mode !== 'receive' && d.stockId === null) return t('assets.stock.site_needed');
  if (d.quantity === null || d.quantity === '' || Number(d.quantity) === 0) {
    return t('assets.stock.quantity_needed');
  }
  if (mode === 'allocate' && d.recipientId === null) return t('assets.stock.recipient_needed');
  if (batches && mode === 'receive' && d.lot.trim() === '') return t('assets.stock.lot_needed');
  if (batches && mode !== 'receive' && d.batchId === null) return t('assets.stock.batch_needed');
  if (mode === 'adjust' && d.comment.trim() === '') return t('assets.stock.reason_needed');
  return undefined;
}

/**
 * Receive, allocate, adjust or take back stock (REQ-AST-033, 034). An allocation that would take
 * more than there is comes back refused with the amount available, shown here.
 */
export function StockDialog({
  consumable,
  mode,
  workItemId,
  onClose,
}: {
  consumable: AssetConsumableDetail;
  mode: StockMode | undefined;
  workItemId?: string;
  onClose: () => void;
}) {
  const t = useLabel();
  const siteName = useSiteNames();
  const actions = useConsumableActions();
  const [d, setD] = useState<Draft>(EMPTY);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [problem, setProblem] = useState<string | null>(null);
  const edit = (next: Partial<Draft>) => {
    setD((now) => ({ ...now, ...next }));
  };
  const close = () => {
    setD(EMPTY);
    setProblem(null);
    setKey(crypto.randomUUID());
    onClose();
  };
  const batches = consumable.batch_tracked;
  const lots = consumable.batches.filter((b) => b.stock_id === d.stockId);
  const pending =
    actions.receive.isPending ||
    actions.allocate.isPending ||
    actions.adjust.isPending ||
    actions.returnStock.isPending;
  const failed = (error: unknown) => {
    setProblem(problemText(t, error));
  };
  const submit = () => {
    if (mode === undefined || d.quantity === null) return;
    setProblem(null);
    const comment = d.comment.trim() || null;
    const done = { onSuccess: close, onError: failed };
    const id = consumable.id;
    if (mode === 'receive') {
      actions.receive.mutate(
        {
          id,
          key,
          body: {
            site_id: d.siteId,
            quantity: d.quantity,
            batch: batches
              ? {
                  lot_number: d.lot.trim(),
                  reference: d.reference.trim() || null,
                  manufactured_on: iso(d.made),
                  expires_on: iso(d.expires),
                }
              : null,
            location: d.location.trim() || null,
            unit_cost: d.cost,
            happened_on: iso(d.day),
            comment,
          },
        },
        done,
      );
    } else if (mode === 'allocate' && d.stockId !== null && d.recipientId !== null) {
      actions.allocate.mutate(
        {
          id,
          key,
          body: {
            stock_id: d.stockId,
            quantity: d.quantity,
            recipient_kind: d.recipientKind,
            recipient_id: d.recipientId,
            work_item_id: workItemId ?? null,
            batch_id: d.batchId,
            happened_on: iso(d.day),
            comment,
          },
        },
        done,
      );
    } else if (mode === 'adjust' && d.stockId !== null) {
      actions.adjust.mutate(
        {
          id,
          key,
          body: {
            stock_id: d.stockId,
            change: d.quantity,
            batch_id: d.batchId,
            comment: comment ?? '',
          },
        },
        done,
      );
    } else if (mode === 'return' && d.stockId !== null) {
      actions.returnStock.mutate(
        {
          id,
          key,
          body: { stock_id: d.stockId, quantity: d.quantity, batch_id: d.batchId, comment },
        },
        done,
      );
    }
  };
  const quantityLabel = mode === 'adjust' ? t('assets.stock.change') : t('assets.stock.quantity');
  return (
    <Modal
      open={mode !== undefined}
      title={mode === undefined ? '' : t(`assets.stock.${mode}_title`)}
      cancelText={t('actions.cancel')}
      onCancel={close}
      footer={okFooter({
        okText: mode === undefined ? '' : t(`assets.stock.${mode}`),
        loading: pending,
        whyDisabled: mode === undefined ? undefined : whyNot(t, mode, d, batches),
        testId: 'stock-dialog-save',
        onOk: submit,
      })}
      destroyOnHidden
      data-testid="stock-dialog"
    >
      {problem !== null && (
        <Alert
          type="error"
          showIcon
          message={problem}
          style={{ marginBottom: 12 }}
          data-testid="stock-dialog-problem"
        />
      )}
      {workItemId !== undefined && mode === 'allocate' && (
        <Alert
          type="info"
          showIcon
          message={t('assets.stock.for_request')}
          style={{ marginBottom: 12 }}
        />
      )}
      <Form layout="vertical" component="div">
        {mode === 'receive' ? (
          <Form.Item label={t('assets.stock.site')}>
            <SitePicker
              value={d.siteId}
              onChange={(siteId) => {
                edit({ siteId });
              }}
              ariaLabel={t('assets.stock.site')}
              testId="stock-dialog-site"
            />
          </Form.Item>
        ) : (
          <Form.Item label={t('assets.stock.from_site')} required>
            <Select
              value={d.stockId}
              aria-label={t('assets.stock.from_site')}
              onChange={(stockId: string) => {
                edit({ stockId, batchId: null });
              }}
              options={consumable.stocks.map((s) => ({
                value: s.id,
                label: `${siteName(s.site_id)} (${plainQuantity(s.quantity)})`,
              }))}
              data-testid="stock-dialog-stock"
            />
          </Form.Item>
        )}
        <Form.Item
          label={quantityLabel}
          required
          extra={mode === 'adjust' ? t('assets.stock.change_help') : undefined}
          htmlFor="stock-dialog-quantity"
        >
          <InputNumber<string>
            id="stock-dialog-quantity"
            stringMode
            min={mode === 'adjust' ? undefined : '0'}
            step="1"
            value={d.quantity}
            onChange={(quantity) => {
              edit({ quantity });
            }}
            data-testid="stock-dialog-quantity"
          />
        </Form.Item>
        {mode === 'allocate' && (
          <>
            <Form.Item label={t('assets.stock.allocate_to')}>
              <Segmented<AssetRecipientKind>
                value={d.recipientKind}
                onChange={(recipientKind) => {
                  edit({ recipientKind, recipientId: null });
                }}
                options={RECIPIENTS.map((kind) => ({
                  value: kind,
                  label: t(`asset_recipient_kind.${kind}`),
                }))}
                data-testid="stock-dialog-recipient-kind"
              />
            </Form.Item>
            <Form.Item label={t(`asset_recipient_kind.${d.recipientKind}`)} required>
              {d.recipientKind === 'user' ? (
                <UserPicker
                  value={d.recipientId}
                  onChange={(recipientId) => {
                    edit({ recipientId });
                  }}
                  testId="stock-dialog-recipient"
                  ariaLabel={t('asset_recipient_kind.user')}
                />
              ) : d.recipientKind === 'department' ? (
                <DepartmentPicker
                  value={d.recipientId}
                  onChange={(recipientId) => {
                    edit({ recipientId });
                  }}
                  testId="stock-dialog-recipient"
                  ariaLabel={t('asset_recipient_kind.department')}
                />
              ) : (
                <AssetPicker
                  value={d.recipientId ?? undefined}
                  onChange={(recipientId) => {
                    edit({ recipientId: recipientId ?? null });
                  }}
                  exclude=""
                  testId="stock-dialog-recipient"
                  ariaLabel={t('asset_recipient_kind.asset')}
                />
              )}
            </Form.Item>
          </>
        )}
        {batches && mode === 'receive' && (
          <Flex gap={16} wrap>
            <Form.Item label={t('assets.stock.lot')} required htmlFor="stock-dialog-lot">
              <Input
                id="stock-dialog-lot"
                dir="ltr"
                value={d.lot}
                count={lengthLimit(120)}
                onChange={(event) => {
                  edit({ lot: event.target.value });
                }}
                data-testid="stock-dialog-lot"
              />
            </Form.Item>
            <Form.Item label={t('assets.stock.reference')} htmlFor="stock-dialog-reference">
              <Input
                id="stock-dialog-reference"
                dir="ltr"
                value={d.reference}
                onChange={(event) => {
                  edit({ reference: event.target.value });
                }}
              />
            </Form.Item>
            <Form.Item label={t('assets.stock.manufactured')}>
              <DatePicker
                value={d.made}
                onChange={(made) => {
                  edit({ made });
                }}
                aria-label={t('assets.stock.manufactured')}
              />
            </Form.Item>
            <Form.Item label={t('assets.stock.expires')}>
              <DatePicker
                value={d.expires}
                onChange={(expires) => {
                  edit({ expires });
                }}
                aria-label={t('assets.stock.expires')}
                data-testid="stock-dialog-expires"
              />
            </Form.Item>
          </Flex>
        )}
        {batches && mode !== 'receive' && (
          <Form.Item label={t('assets.stock.batch')} required>
            <Select
              value={d.batchId}
              aria-label={t('assets.stock.batch')}
              onChange={(batchId: string) => {
                edit({ batchId });
              }}
              notFoundContent={<EmptyText>{t('assets.stock.no_batches')}</EmptyText>}
              options={lots.map((b) => ({
                value: b.id,
                label: `${b.lot_number} (${plainQuantity(b.quantity)})`,
              }))}
              data-testid="stock-dialog-batch"
            />
          </Form.Item>
        )}
        {mode === 'receive' && (
          <Flex gap={16} wrap>
            <Form.Item label={t('assets.stock.location')} htmlFor="stock-dialog-location">
              <Input
                id="stock-dialog-location"
                value={d.location}
                count={lengthLimit(200)}
                onChange={(event) => {
                  edit({ location: event.target.value });
                }}
              />
            </Form.Item>
            <Form.Item label={t('assets.stock.unit_cost')} htmlFor="stock-dialog-cost">
              <InputNumber<string>
                id="stock-dialog-cost"
                stringMode
                min="0"
                step="0.01"
                value={d.cost}
                onChange={(cost) => {
                  edit({ cost });
                }}
              />
            </Form.Item>
          </Flex>
        )}
        {(mode === 'receive' || mode === 'allocate') && (
          <Form.Item label={t('assets.stock.date')}>
            <DatePicker
              value={d.day}
              onChange={(day) => {
                edit({ day });
              }}
              disabledDate={(day) => day.isAfter(dayjs(), 'day')}
              aria-label={t('assets.stock.date')}
            />
          </Form.Item>
        )}
        <Form.Item
          label={mode === 'adjust' ? t('assets.stock.reason') : t('assets.stock.comment')}
          required={mode === 'adjust'}
        >
          <Input.TextArea
            aria-label={mode === 'adjust' ? t('assets.stock.reason') : t('assets.stock.comment')}
            value={d.comment}
            count={lengthLimit(COMMENT_MAX)}
            autoSize={{ minRows: 2, maxRows: 5 }}
            onChange={(event) => {
              edit({ comment: event.target.value });
            }}
            data-testid="stock-dialog-comment"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

const MOVEMENT_TONE = {
  receive: 'success',
  allocate: 'info',
  adjust: 'warning',
  return: 'default',
} as const;

function Ledger({ id }: { id: string }) {
  const t = useLabel();
  const dates = useDateTime();
  const ledger = useConsumableLedger(id);
  return (
    <Table<AssetMovement>
      size="small"
      rowKey="id"
      loading={ledger.isPending}
      dataSource={ledger.data ?? []}
      pagination={false}
      scroll={{ x: 'max-content' }}
      locale={{ emptyText: loadedEmpty(ledger.isPending, t('assets.stock.no_movements')) }}
      data-testid="consumable-ledger"
      columns={[
        {
          key: 'when',
          title: t('assets.stock.date'),
          render: (_, row) => (
            <span style={{ whiteSpace: 'nowrap' }}>{dates.formatDay(row.happened_on)}</span>
          ),
        },
        {
          key: 'kind',
          title: t('assets.stock.movement'),
          render: (_, row) => (
            <ToneTag tone={MOVEMENT_TONE[row.kind]}>{t(`asset_movement_kind.${row.kind}`)}</ToneTag>
          ),
        },
        {
          key: 'quantity',
          title: t('assets.stock.quantity'),
          align: 'end',
          render: (_, row) =>
            row.kind === 'adjust' ? plainQuantity(row.quantity) : unsignedQuantity(row.quantity),
        },
        {
          key: 'balance',
          title: t('assets.stock.balance'),
          align: 'end',
          render: (_, row) => plainQuantity(row.balance_after),
        },
        {
          key: 'who',
          title: t('assets.stock.to_from'),
          render: (_, row) => (
            <Flex vertical gap={0}>
              <Recipient row={row} />
              {row.work_item_id !== null && (
                <Link to={`/requests/${row.work_item_id}`}>{t('assets.stock.request')}</Link>
              )}
            </Flex>
          ),
        },
        {
          key: 'by',
          title: t('assets.stock.by'),
          render: (_, row) => (row.created_by === null ? null : <PersonName id={row.created_by} />),
        },
        {
          key: 'comment',
          title: t('assets.stock.comment'),
          render: (_, row) => (
            <CellText title={row.comment ?? undefined}>
              {row.comment === null ? '' : <bdi dir="auto">{row.comment}</bdi>}
            </CellText>
          ),
        },
      ]}
    />
  );
}

function Stocks({ consumable, loading }: { consumable: AssetConsumableDetail; loading: boolean }) {
  const t = useLabel();
  const siteName = useSiteNames();
  return (
    <Table<AssetStock>
      size="small"
      rowKey="id"
      loading={loading}
      dataSource={consumable.stocks}
      pagination={false}
      scroll={{ x: 'max-content' }}
      locale={{ emptyText: loadedEmpty(loading, t('assets.stock.no_stock')) }}
      data-testid="consumable-stocks"
      columns={[
        {
          key: 'site',
          title: t('assets.stock.site'),
          render: (_, s) => <bdi dir="auto">{siteName(s.site_id)}</bdi>,
        },
        {
          key: 'location',
          title: t('assets.stock.location'),
          render: (_, s) => <CellText>{s.location ?? ''}</CellText>,
        },
        {
          key: 'quantity',
          title: t('assets.stock.quantity'),
          align: 'end',
          render: (_, s) => (
            <span data-testid={`stock-quantity-${s.id}`}>{plainQuantity(s.quantity)}</span>
          ),
        },
        {
          key: 'minimum',
          title: t('assets.stock.minimum'),
          align: 'end',
          render: (_, s) => (s.minimum === null ? '' : plainQuantity(s.minimum)),
        },
        {
          key: 'low',
          title: t('assets.stock.state'),
          render: (_, s) => {
            const level = stockLevelKey(s);
            return level === null ? null : (
              <ToneTag tone="warning" testId={`stock-low-${s.id}`}>
                {t(level)}
              </ToneTag>
            );
          },
        },
      ]}
    />
  );
}

function Batches({ consumable, loading }: { consumable: AssetConsumableDetail; loading: boolean }) {
  const t = useLabel();
  const dates = useDateTime();
  const siteName = useSiteNames();
  return (
    <Table<AssetBatch>
      size="small"
      rowKey="id"
      loading={loading}
      dataSource={consumable.batches}
      pagination={false}
      scroll={{ x: 'max-content' }}
      locale={{ emptyText: loadedEmpty(loading, t('assets.stock.no_batches')) }}
      data-testid="consumable-batches"
      columns={[
        {
          key: 'lot',
          title: t('assets.stock.lot'),
          render: (_, b) => <bdi dir="ltr">{b.lot_number}</bdi>,
        },
        {
          key: 'site',
          title: t('assets.stock.site'),
          render: (_, b) => <bdi dir="auto">{siteName(b.site_id)}</bdi>,
        },
        {
          key: 'quantity',
          title: t('assets.stock.quantity'),
          align: 'end',
          render: (_, b) => plainQuantity(b.quantity),
        },
        {
          key: 'made',
          title: t('assets.stock.manufactured'),
          render: (_, b) => (b.manufactured_on === null ? '' : dates.formatDay(b.manufactured_on)),
        },
        {
          key: 'expires',
          title: t('assets.stock.expires'),
          render: (_, b) => (
            <Flex gap={4} wrap>
              {b.expires_on === null ? '' : dates.formatDay(b.expires_on)}
              {b.expired && (
                <ToneTag tone="error" testId={`batch-expired-${b.id}`}>
                  {t('assets.stock.expired')}
                </ToneTag>
              )}
            </Flex>
          ),
        },
      ]}
    />
  );
}

/**
 * One consumable (WP-049b s1; REQ-AST-033, 034): its stock per site, its lots with their expiry
 * (an expired lot flagged), and the ledger; receive, allocate, adjust and take back. Opened with
 * `?allocate_for=<request>`, the allocation is linked to that request (034 AC2). Live (rule c).
 */
export function ConsumablePage() {
  const t = useLabel();
  const navigate = useNavigate();
  const { id } = useParams();
  const [params] = useSearchParams();
  const access = useAccess();
  const allowed = access.can('assets.view');
  const found = useConsumable(allowed ? id : undefined);
  const forRequest = params.get('allocate_for') ?? undefined;
  const [mode, setMode] = useState<StockMode | undefined>(
    forRequest === undefined ? undefined : 'allocate',
  );
  useConsumablesLive();
  // The unit cost is in the base currency (stock.py), shown with it as assets show theirs (F-15).
  const money = useMoney(useTenantSettings(allowed).data?.base_currency);
  // The path in the top bar and the tab's title: Consumables › Toner 26A (lane C's #367 review).
  usePageCrumbs([
    { label: t('assets.stock.title'), path: '/assets/consumables' },
    ...(found.data ? [{ label: found.data.product_name }] : []),
  ]);
  if (!allowed) return <NoAccess titleKey="nav.assets" />;
  if (found.isPending) return <Skeleton active />;
  const consumable = found.data;
  if (consumable === undefined) {
    return <Alert type="warning" showIcon message={t('errors.asset_consumable_not_found')} />;
  }
  const manage = access.can('assets.manage');
  const held = consumable.stocks.some((s) => Number(s.quantity) > 0);
  const why = manage ? undefined : t('assets.stock.manage_needed');
  const actions: RecordAction[] = (['receive', 'allocate', 'adjust', 'return'] as const).map(
    (key, rank) => ({
      key,
      label: t(`assets.stock.${key}`),
      allowed: manage && (key === 'receive' || consumable.stocks.length > 0),
      whyNot: why ?? (key === 'receive' ? undefined : t('assets.stock.receive_first')),
      onClick: () => {
        setMode(key);
      },
      primary: key === 'receive' || key === 'allocate',
      rank,
    }),
  );
  // Below the minimum at any site says so; only "At minimum" when none is below (F-15).
  const levels = consumable.stocks.map(stockLevelKey);
  const level = levels.includes('assets.stock.below_minimum')
    ? 'assets.stock.below_minimum'
    : levels.includes('assets.stock.low')
      ? 'assets.stock.low'
      : null;
  return (
    <RecordPage
      testId="consumable-page"
      header={
        <RecordHeader
          icon={<InboxOutlined />}
          kind="asset"
          typeLabel={t('assets.stock.record_type')}
          displayId={consumable.barcode ?? t('assets.stock.no_barcode')}
          copyable={consumable.barcode !== null}
          title={consumable.product_name}
          testIds={{ id: 'consumable-barcode', title: 'consumable-heading' }}
          tags={
            <>
              {consumable.batch_tracked && (
                <ToneTag tone="default">{t('assets.stock.batches')}</ToneTag>
              )}
              {level !== null && (
                <ToneTag tone="warning" testId="consumable-low">
                  {t(level)}
                </ToneTag>
              )}
            </>
          }
        />
      }
      actions={<ActionBar actions={actions} max={2} testId="consumable-actions" />}
      alerts={
        !held && consumable.stocks.length > 0 ? (
          <Alert
            type="warning"
            showIcon
            role="status"
            message={t('assets.stock.all_out')}
            data-testid="consumable-all-out"
          />
        ) : undefined
      }
      panel={
        <PropertiesPanel
          testId="consumable-panel"
          sections={[
            {
              key: 'details',
              title: t('assets.record.details'),
              children: (
                <PropertyList
                  testId="consumable-props"
                  items={[
                    {
                      key: 'total',
                      label: t('assets.stock.total'),
                      content: plainQuantity(consumable.total),
                      filled: true,
                    },
                    {
                      key: 'batches',
                      label: t('assets.stock.batch_tracked'),
                      content: t(consumable.batch_tracked ? 'assets.stock.yes' : 'assets.stock.no'),
                      filled: true,
                    },
                    {
                      key: 'cost',
                      label: t('assets.stock.unit_cost'),
                      testId: 'consumable-unit-cost',
                      content: money(consumable.unit_cost) ?? '',
                      filled: consumable.unit_cost !== null,
                    },
                    {
                      key: 'comment',
                      label: t('assets.stock.comment'),
                      content: <bdi dir="auto">{consumable.comment ?? ''}</bdi>,
                      filled: consumable.comment !== null,
                    },
                  ]}
                />
              ),
            },
          ]}
        />
      }
    >
      <StockDialog
        consumable={consumable}
        mode={mode}
        workItemId={forRequest}
        onClose={() => {
          setMode(undefined);
          if (forRequest !== undefined) void navigate(`/assets/consumables/${consumable.id}`);
        }}
      />
      <Tabs
        items={[
          {
            key: 'stock',
            label: t('assets.stock.by_site'),
            children: (
              <Flex vertical gap={16}>
                <Stocks consumable={consumable} loading={found.isPending} />
                {consumable.batch_tracked && (
                  <section aria-labelledby="consumable-batches-title">
                    <Typography.Title level={5} id="consumable-batches-title">
                      {t('assets.stock.batches')}
                    </Typography.Title>
                    <Batches consumable={consumable} loading={found.isPending} />
                  </section>
                )}
              </Flex>
            ),
          },
          {
            key: 'ledger',
            label: t('assets.stock.ledger'),
            children: <Ledger id={consumable.id} />,
          },
        ]}
        data-testid="consumable-tabs"
      />
    </RecordPage>
  );
}
