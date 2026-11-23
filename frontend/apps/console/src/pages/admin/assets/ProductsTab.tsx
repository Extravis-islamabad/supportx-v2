import {
  Button,
  Card,
  Checkbox,
  Flex,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Table,
  TreeSelect,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';

import {
  useAssetProducts,
  type AssetDepreciationMethod,
  type AssetProduct,
  type AssetProductInput,
  type AssetProductType,
} from '@supportx/api-client';
import {
  EmptyText,
  lengthLimit,
  useAccess,
  useAppearance,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { Problems } from '../incidents/shared';
import { nameOf, useCatalogueSave } from './shared';
import { typeTree, type TypeNode } from './tree';

const METHODS: AssetDepreciationMethod[] = [
  'straight_line',
  'declining_balance',
  'double_declining_balance',
  'sum_of_years_digits',
];

// The product form's text and number fields; amounts travel as decimal strings (no float).
interface Draft {
  product_type_id: string;
  name: string;
  manufacturer: string;
  part_number: string;
  price: string | null;
  tax: string | null;
  currency: string;
  gl_code: string;
  hide_from_purchase_orders: boolean;
  depreciation_method: AssetDepreciationMethod | null;
  useful_life_years: number | null;
  salvage_value: string | null;
  description: string;
}

const TEXT = ['name', 'manufacturer', 'part_number', 'gl_code', 'description'] as const;

function draftOf(product: AssetProduct | null, typeId: string): Draft {
  return {
    product_type_id: product?.product_type_id ?? typeId,
    name: product?.name ?? '',
    manufacturer: product?.manufacturer ?? '',
    part_number: product?.part_number ?? '',
    price: product?.price ?? null,
    tax: product?.tax ?? null,
    currency: product?.currency ?? '',
    gl_code: product?.gl_code ?? '',
    hide_from_purchase_orders: product?.hide_from_purchase_orders ?? false,
    depreciation_method: product?.depreciation_method ?? null,
    useful_life_years: product?.useful_life_years ?? null,
    salvage_value: product?.salvage_value ?? null,
    description: product?.description ?? '',
  };
}

/** What the form sends: blanks as null, the currency upper-cased. */
function bodyOf(draft: Draft): AssetProductInput {
  const blank = (value: string) => (value.trim() === '' ? null : value.trim());
  return {
    product_type_id: draft.product_type_id,
    name: draft.name.trim(),
    manufacturer: blank(draft.manufacturer),
    part_number: blank(draft.part_number),
    price: draft.price,
    tax: draft.tax,
    currency: blank(draft.currency.toUpperCase()),
    gl_code: blank(draft.gl_code),
    hide_from_purchase_orders: draft.hide_from_purchase_orders,
    depreciation_method: draft.depreciation_method,
    useful_life_years: draft.useful_life_years,
    salvage_value: draft.salvage_value,
    description: blank(draft.description),
  };
}

/**
 * Products: what can be bought or held, each of one product type. Price and tax are stored
 * apart and the total is worked out (D-141), so a tax change never edits a price. The list
 * pages through the server and can show one type's products.
 */
export function ProductsTab({ types }: { types: AssetProductType[] }) {
  const t = useLabel();
  const { locale, intlLocale } = useAppearance();
  // D-157 2b: list prices and default depreciation are money (assets.view_financials); the
  // API sends them as null to others, so the screen leaves them out.
  const seesMoney = useAccess().can('assets.view_financials');
  const [typeId, setTypeId] = useState<string>();
  const products = useAssetProducts({ productTypeId: typeId });
  const { run, problems, clear, pending } = useCatalogueSave();
  const [editing, setEditing] = useState<AssetProduct | 'new' | null>(null);
  const [draft, setDraft] = useState<Draft>();
  const [key, setKey] = useState(() => crypto.randomUUID());
  const tree = useMemo(() => typeTree(types), [types]);
  const choices = (nodes: TypeNode[]): object[] =>
    nodes.map((node) => ({
      value: node.id,
      title: nameOf(node.names, locale),
      children: choices(node.children ?? []),
    }));
  const typeName = (id: string) => {
    const type = types.find((x) => x.id === id);
    return type === undefined ? '' : nameOf(type.names, locale);
  };
  const money = (amount: string | null, currency: string | null) => {
    if (amount === null) return '';
    const number = Number(amount);
    return currency === null
      ? new Intl.NumberFormat(intlLocale, { minimumFractionDigits: 2 }).format(number)
      : new Intl.NumberFormat(intlLocale, { style: 'currency', currency }).format(number);
  };
  const rows = products.data?.pages.flatMap((page) => page.items) ?? [];
  const open = (product: AssetProduct | 'new') => {
    clear();
    setKey(crypto.randomUUID());
    setEditing(product);
    setDraft(draftOf(product === 'new' ? null : product, typeId ?? types[0]?.id ?? ''));
  };
  const close = () => {
    clear();
    setEditing(null);
  };
  const save = () => {
    if (draft === undefined || editing === null) return;
    const body = bodyOf(draft);
    if (editing === 'new') {
      run({ kind: 'create_product', key, body }, close);
      return;
    }
    const before = bodyOf(draftOf(editing, editing.product_type_id));
    // Only what changed (a cleared field is sent as null).
    const changed = Object.fromEntries(
      Object.entries(body).filter(([k, v]) => v !== before[k as keyof AssetProductInput]),
    );
    run({ kind: 'product', id: editing.id, version: editing.version, body: changed }, close, close);
  };
  const amount = (field: 'price' | 'tax' | 'salvage_value', label: string) =>
    draft === undefined ? null : (
      <Form.Item label={label} htmlFor={`asset-product-${field}`}>
        <InputNumber<string>
          id={`asset-product-${field}`}
          stringMode
          min="0"
          step="0.01"
          precision={2}
          value={draft[field]}
          onChange={(value) => {
            setDraft({ ...draft, [field]: value === '' ? null : value });
          }}
          style={{ width: 160 }}
          data-testid={`asset-product-${field}`}
        />
      </Form.Item>
    );
  return (
    <Card
      title={t('assets.admin.products')}
      extra={
        <WriteButton
          disabled={types.length === 0}
          whyDisabled={t('assets.admin.types_needed')}
          onClick={() => {
            open('new');
          }}
          data-testid="asset-product-add"
        >
          {t('actions.add')}
        </WriteButton>
      }
      data-testid="asset-products"
    >
      <Flex vertical gap={12}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {t('assets.admin.products_help')}
        </Typography.Paragraph>
        <TreeSelect
          aria-label={t('assets.admin.product_type')}
          allowClear
          placeholder={t('assets.admin.all_types')}
          value={typeId}
          treeData={choices(tree)}
          onChange={(id: string | undefined) => {
            setTypeId(id);
          }}
          style={{ maxWidth: 320 }}
          data-testid="asset-product-filter"
        />
        {editing === null && <Problems problems={problems} testId="asset-products-problems" />}
        <Table
          size="small"
          rowKey="id"
          pagination={false}
          loading={products.isLoading}
          dataSource={rows}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: <EmptyText>{t('assets.admin.no_products')}</EmptyText> }}
          columns={[
            {
              key: 'name',
              title: t('settings.name'),
              render: (_: unknown, product: AssetProduct) => <bdi dir="auto">{product.name}</bdi>,
            },
            {
              key: 'type',
              title: t('assets.admin.product_type'),
              render: (_: unknown, product: AssetProduct) => (
                <bdi dir="auto">{typeName(product.product_type_id)}</bdi>
              ),
            },
            {
              key: 'manufacturer',
              title: t('assets.admin.manufacturer'),
              render: (_: unknown, product: AssetProduct) => (
                <bdi dir="auto">{product.manufacturer ?? ''}</bdi>
              ),
            },
            ...(seesMoney
              ? [
                  {
                    key: 'price',
                    title: t('assets.admin.price'),
                    align: 'end' as const,
                    render: (_: unknown, product: AssetProduct) =>
                      money(product.price, product.currency),
                  },
                  {
                    key: 'total',
                    title: t('assets.admin.total'),
                    align: 'end' as const,
                    render: (_: unknown, product: AssetProduct) => (
                      <span data-testid={`asset-product-total-${product.id}`}>
                        {money(product.total, product.currency)}
                      </span>
                    ),
                  },
                ]
              : []),
            {
              key: 'actions',
              title: <span className="sr-only">{t('assets.admin.actions')}</span>,
              render: (_: unknown, product: AssetProduct) => (
                <Flex gap={4} justify="end">
                  <Button
                    type="link"
                    onClick={() => {
                      open(product);
                    }}
                  >
                    {t('actions.edit')}
                  </Button>
                  <Popconfirm
                    title={t('assets.admin.delete_confirm', { name: product.name })}
                    okText={t('actions.delete')}
                    cancelText={t('actions.cancel')}
                    onConfirm={() => {
                      run({ kind: 'delete_product', id: product.id, version: product.version });
                    }}
                  >
                    <Button type="link" danger>
                      {t('actions.delete')}
                    </Button>
                  </Popconfirm>
                </Flex>
              ),
            },
          ]}
        />
        {products.hasNextPage && (
          <Button
            onClick={() => {
              void products.fetchNextPage();
            }}
            loading={products.isFetchingNextPage}
            style={{ alignSelf: 'center' }}
            data-testid="asset-products-more"
          >
            {t('assets.admin.load_more')}
          </Button>
        )}
      </Flex>
      <Modal
        open={editing !== null}
        width={720}
        title={editing === 'new' ? t('assets.admin.add_product') : t('assets.admin.edit_product')}
        okText={t('actions.save')}
        cancelText={t('actions.cancel')}
        onOk={save}
        onCancel={close}
        confirmLoading={pending}
        destroyOnHidden
        data-testid="asset-product-dialog"
      >
        {draft !== undefined && editing !== null && (
          <Form layout="vertical">
            <Problems problems={problems} testId="asset-product-problems" />
            <Form.Item label={t('assets.admin.product_type')} htmlFor="asset-product-type" required>
              <TreeSelect
                id="asset-product-type"
                aria-label={t('assets.admin.product_type')}
                value={draft.product_type_id}
                treeData={choices(tree)}
                treeDefaultExpandAll
                onChange={(id: string) => {
                  setDraft({ ...draft, product_type_id: id });
                }}
                data-testid="asset-product-type"
              />
            </Form.Item>
            {TEXT.map((field) => (
              <Form.Item
                key={field}
                label={t(`assets.admin.${field}`)}
                htmlFor={`asset-product-${field}`}
                required={field === 'name'}
              >
                {field === 'description' ? (
                  <Input.TextArea
                    id={`asset-product-${field}`}
                    dir="auto"
                    rows={2}
                    count={lengthLimit(2000)}
                    value={draft[field]}
                    onChange={(event) => {
                      setDraft({ ...draft, [field]: event.target.value });
                    }}
                  />
                ) : (
                  <Input
                    id={`asset-product-${field}`}
                    dir="auto"
                    count={lengthLimit(
                      field === 'gl_code' ? 40 : field === 'part_number' ? 100 : 200,
                    )}
                    value={draft[field]}
                    onChange={(event) => {
                      setDraft({ ...draft, [field]: event.target.value });
                    }}
                    data-testid={`asset-product-${field}`}
                  />
                )}
              </Form.Item>
            ))}
            <Flex gap={16} wrap>
              {seesMoney && amount('price', t('assets.admin.price'))}
              {seesMoney && amount('tax', t('assets.admin.tax'))}
              <Form.Item label={t('assets.admin.currency')} htmlFor="asset-product-currency">
                <Input
                  id="asset-product-currency"
                  dir="ltr"
                  count={lengthLimit(3)}
                  value={draft.currency}
                  onChange={(event) => {
                    setDraft({ ...draft, currency: event.target.value.toUpperCase() });
                  }}
                  style={{ width: 96 }}
                  data-testid="asset-product-currency"
                />
              </Form.Item>
            </Flex>
            {seesMoney && (
              <Flex gap={16} wrap>
                <Form.Item label={t('assets.admin.depreciation')} htmlFor="asset-product-method">
                  <Select
                    id="asset-product-method"
                    aria-label={t('assets.admin.depreciation')}
                    allowClear
                    value={draft.depreciation_method ?? undefined}
                    onChange={(method: AssetDepreciationMethod | undefined) => {
                      setDraft({ ...draft, depreciation_method: method ?? null });
                    }}
                    options={METHODS.map((code) => ({
                      value: code,
                      label: t(`asset_depreciation.${code}`),
                    }))}
                    style={{ minWidth: 220 }}
                  />
                </Form.Item>
                <Form.Item label={t('assets.admin.useful_life')} htmlFor="asset-product-life">
                  <InputNumber
                    id="asset-product-life"
                    min={1}
                    max={100}
                    value={draft.useful_life_years}
                    onChange={(value) => {
                      setDraft({ ...draft, useful_life_years: value });
                    }}
                  />
                </Form.Item>
                {amount('salvage_value', t('assets.admin.salvage_value'))}
              </Flex>
            )}
            <Checkbox
              checked={draft.hide_from_purchase_orders}
              onChange={(event) => {
                setDraft({ ...draft, hide_from_purchase_orders: event.target.checked });
              }}
            >
              {t('assets.admin.hide_from_purchase_orders')}
            </Checkbox>
          </Form>
        )}
      </Modal>
    </Card>
  );
}
