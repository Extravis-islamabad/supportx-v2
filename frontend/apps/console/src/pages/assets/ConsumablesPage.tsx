import {
  Alert,
  Card,
  Flex,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Typography,
} from 'antd';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  useAssetProducts,
  useAssetProductTypes,
  useConsumableActions,
  useConsumables,
  useVendors,
  type AssetConsumable,
} from '@supportx/api-client';
import {
  CellText,
  EmptyText,
  FilterBar,
  lengthLimit,
  ListPage,
  NoAccess,
  PageHeader,
  ToneTag,
  useAccess,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { SitePicker } from '../incidents/pickers';
import { okFooter } from './dialogOk';
import { problemText } from './problemText';
import { useConsumablesLive, useSiteNames } from './live';
import { plainQuantity } from './quantity';

const COMMENT_MAX = 2000;
/** A new consumable: a product of a consumable type; batch tracking is chosen now, for good. */
function NewConsumableDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useLabel();
  const navigate = useNavigate();
  const { create } = useConsumableActions();
  const types = useAssetProductTypes(open);
  const [search, setSearch] = useState('');
  const searched = useDebounced(search, 250);
  const products = useAssetProducts({ search: searched === '' ? undefined : searched }, open);
  const [product, setProduct] = useState<string | null>(null);
  const [batches, setBatches] = useState(false);
  const [barcode, setBarcode] = useState('');
  const [vendor, setVendor] = useState<string | null>(null);
  const vendors = useVendors(true, open);
  const [cost, setCost] = useState<string | null>(null);
  const [comment, setComment] = useState('');
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [problem, setProblem] = useState<string | null>(null);
  const consumableTypes = new Set(
    (types.data ?? []).filter((x) => x.kind === 'consumable').map((x) => x.id),
  );
  const offered = (products.data?.pages.flatMap((p) => p.items) ?? []).filter((p) =>
    consumableTypes.has(p.product_type_id),
  );
  const close = () => {
    setProduct(null);
    setBatches(false);
    setBarcode('');
    setVendor(null);
    setCost(null);
    setComment('');
    setProblem(null);
    setKey(crypto.randomUUID());
    onClose();
  };
  return (
    <Modal
      open={open}
      title={t('assets.stock.new')}
      cancelText={t('actions.cancel')}
      onCancel={close}
      footer={okFooter({
        okText: t('actions.save'),
        loading: create.isPending,
        whyDisabled: product === null ? t('assets.stock.product_needed') : undefined,
        testId: 'consumable-new-save',
        onOk: () => {
          if (product === null) return;
          setProblem(null);
          create.mutate(
            {
              key,
              body: {
                product_id: product,
                batch_tracked: batches,
                barcode: barcode.trim() || null,
                vendor_id: vendor,
                unit_cost: cost,
                comment: comment.trim() || null,
              },
            },
            {
              onSuccess: (made) => {
                close();
                void navigate(`/assets/consumables/${made.id}`);
              },
              onError: (error) => {
                setProblem(problemText(t, error));
              },
            },
          );
        },
      })}
      destroyOnHidden
      data-testid="consumable-new"
    >
      {problem !== null && (
        <Alert type="error" showIcon message={problem} style={{ marginBottom: 12 }} />
      )}
      <Form layout="vertical" component="div">
        <Form.Item
          label={t('assets.stock.product')}
          required
          extra={t('assets.stock.product_help')}
        >
          <Select
            showSearch
            filterOption={false}
            value={product}
            onSearch={setSearch}
            onChange={setProduct}
            loading={products.isFetching}
            aria-label={t('assets.stock.product')}
            notFoundContent={<EmptyText>{t('assets.stock.no_products')}</EmptyText>}
            options={offered.map((p) => ({ value: p.id, label: p.name }))}
            data-testid="consumable-new-product"
          />
        </Form.Item>
        <Form.Item
          label={t('assets.stock.batch_tracked')}
          extra={t('assets.stock.batch_tracked_help')}
          htmlFor="consumable-new-batches"
        >
          <Switch
            id="consumable-new-batches"
            checked={batches}
            onChange={setBatches}
            data-testid="consumable-new-batches"
          />
        </Form.Item>
        <Flex gap={16} wrap>
          <Form.Item label={t('assets.stock.barcode')} htmlFor="consumable-new-barcode">
            <Input
              id="consumable-new-barcode"
              dir="ltr"
              value={barcode}
              count={lengthLimit(120)}
              onChange={(event) => {
                setBarcode(event.target.value);
              }}
            />
          </Form.Item>
          <Form.Item label={t('assets.stock.unit_cost')} htmlFor="consumable-new-cost">
            <InputNumber<string>
              id="consumable-new-cost"
              stringMode
              min="0"
              step="0.01"
              value={cost}
              onChange={setCost}
            />
          </Form.Item>
        </Flex>
        <Form.Item label={t('assets.stock.vendor')}>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            value={vendor}
            onChange={(next: string | undefined) => {
              setVendor(next ?? null);
            }}
            aria-label={t('assets.stock.vendor')}
            options={(vendors.data?.pages.flatMap((p) => p.items) ?? []).map((v) => ({
              value: v.id,
              label: v.name,
            }))}
            data-testid="consumable-new-vendor"
          />
        </Form.Item>
        <Form.Item label={t('assets.stock.comment')}>
          <Input.TextArea
            aria-label={t('assets.stock.comment')}
            value={comment}
            count={lengthLimit(COMMENT_MAX)}
            autoSize={{ minRows: 2, maxRows: 5 }}
            onChange={(event) => {
              setComment(event.target.value);
            }}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/**
 * Consumables (WP-049b s1; REQ-AST-033): what is kept in stock, how much at each site, and which
 * have fallen to their minimum. Live from `assets.consumables_changed` (rule c). Built from the
 * shared list parts, like the other asset lists (D-147 template A).
 */
export function ConsumablesPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const access = useAccess();
  const allowed = access.can('assets.view');
  const [search, setSearch] = useState('');
  const [site, setSite] = useState<string | null>(null);
  const searched = useDebounced(search, 250);
  const list = useConsumables({ search: searched, siteId: site ?? undefined }, allowed);
  const siteName = useSiteNames();
  const [adding, setAdding] = useState(false);
  useConsumablesLive();
  if (!allowed) return <NoAccess titleKey="nav.assets" />;
  const rows = list.data ?? [];
  return (
    <ListPage
      testId="consumables-page"
      header={
        <PageHeader
          title={t('assets.stock.title')}
          back={{ label: t('nav.assets'), onClick: () => void navigate('/assets') }}
          count={list.data === undefined ? undefined : String(rows.length)}
          extra={
            access.can('assets.manage') && (
              <WriteButton
                type="primary"
                onClick={() => {
                  setAdding(true);
                }}
                data-testid="consumable-new-open"
              >
                {t('assets.stock.new')}
              </WriteButton>
            )
          }
        />
      }
      filters={
        <FilterBar
          testId="consumables-filterbar"
          search={
            <Input.Search
              allowClear
              aria-label={t('assets.stock.search')}
              placeholder={t('assets.stock.search')}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
              }}
              data-testid="consumables-search"
            />
          }
          quick={
            <div style={{ minWidth: 200 }}>
              <SitePicker
                value={site}
                onChange={setSite}
                ariaLabel={t('assets.stock.site')}
                testId="consumables-site"
              />
            </div>
          }
        />
      }
    >
      <Card>
        <Table<AssetConsumable>
          size="small"
          rowKey="id"
          loading={list.isPending}
          dataSource={rows}
          pagination={false}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: <EmptyText>{t('assets.stock.none')}</EmptyText> }}
          data-testid="consumables"
          columns={[
            {
              key: 'product',
              title: t('assets.stock.product'),
              render: (_, row) => (
                <Space size={4} wrap>
                  <Link to={`/assets/consumables/${row.id}`} data-testid={`consumable-${row.id}`}>
                    <bdi dir="auto">{row.product_name}</bdi>
                  </Link>
                  {row.batch_tracked && (
                    <ToneTag tone="default">{t('assets.stock.batches')}</ToneTag>
                  )}
                </Space>
              ),
            },
            {
              key: 'total',
              title: t('assets.stock.total'),
              align: 'end',
              render: (_, row) => (
                <span data-testid={`consumable-total-${row.id}`}>{plainQuantity(row.total)}</span>
              ),
            },
            {
              key: 'sites',
              title: t('assets.stock.by_site'),
              render: (_, row) => (
                <Flex vertical gap={2}>
                  {row.stocks.map((s) => (
                    <Typography.Text key={s.id}>
                      <bdi dir="auto">{siteName(s.site_id)}</bdi>
                      {`: ${plainQuantity(s.quantity)}`}
                      {s.low && (
                        <>
                          {' '}
                          <ToneTag tone="warning" testId={`consumable-low-${s.id}`}>
                            {t('assets.stock.low')}
                          </ToneTag>
                        </>
                      )}
                    </Typography.Text>
                  ))}
                  {row.stocks.length === 0 && <EmptyText>{t('assets.stock.no_stock')}</EmptyText>}
                </Flex>
              ),
            },
            {
              key: 'barcode',
              title: t('assets.stock.barcode'),
              render: (_, row) => (
                <CellText>
                  {row.barcode === null ? '' : <bdi dir="ltr">{row.barcode}</bdi>}
                </CellText>
              ),
            },
          ]}
        />
      </Card>
      <NewConsumableDialog
        open={adding}
        onClose={() => {
          setAdding(false);
        }}
      />
    </ListPage>
  );
}
