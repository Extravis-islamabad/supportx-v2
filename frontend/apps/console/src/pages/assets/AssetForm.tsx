import { DatePicker, Flex, Form, Input, InputNumber, Select, TreeSelect } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useMemo, useState } from 'react';
import { Link } from 'react-router';

import {
  useAssetProduct,
  useAssetProducts,
  useAssetProductTypes,
  useCustomFields,
  useVendors,
} from '@supportx/api-client';
import { lengthLimit, pickerFormat, useAccess, useAppearance, useLabel } from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { CustomFieldControl } from '../customFields/fields';
import { fieldName } from '../customFields/values';
import { nameOf } from '../admin/assets/shared';
import { typeTree, type TypeNode } from '../admin/assets/tree';
import type { AssetDraft } from './draft';

/**
 * The asset's fields. The product picker is grouped by product type; only active vendors are
 * offered, except the one the asset already names (REQ-PUR-001 AC2). The tag may stay empty on
 * a new asset: the server gives the next one of the pattern (REQ-AST-008).
 */
export function AssetFields({
  draft,
  onChange,
  creating,
}: {
  draft: AssetDraft;
  onChange: (next: AssetDraft) => void;
  creating: boolean;
}) {
  const t = useLabel();
  const access = useAccess();
  const { locale, dates } = useAppearance();
  const types = useAssetProductTypes();
  // Searching picker: the server finds products by name, manufacturer or part number, a page
  // at a time (scrolling loads more); the current one is fetched on its own if not loaded.
  const [productSearch, setProductSearch] = useState('');
  const searched = useDebounced(productSearch, 250);
  const products = useAssetProducts({ search: searched === '' ? undefined : searched });
  const current = useAssetProduct(draft.product_id === '' ? undefined : draft.product_id);
  const vendors = useVendors(false);
  // The tenant's asset custom fields (migration 0083): every active one, in its order.
  const custom = useCustomFields('asset');
  const customFields = (custom.data ?? [])
    .filter((f) => !f.retired && !f.removed)
    .sort((a, b) => a.sort_order - b.sort_order);
  const productChoices = useMemo(() => {
    const rows = products.data?.pages.flatMap((p) => p.items) ?? [];
    const walk = (nodes: TypeNode[]): object[] =>
      nodes.flatMap((node) => {
        const own = [
          ...rows,
          ...(current.data !== undefined && !rows.some((p) => p.id === current.data.id)
            ? [current.data]
            : []),
        ]
          .filter((p) => p.product_type_id === node.id)
          .map((p) => ({ value: p.id, title: p.name }));
        const below = walk(node.children ?? []);
        if (own.length === 0 && below.length === 0) return [];
        return [
          {
            value: `type:${node.id}`,
            title: nameOf(node.names, locale),
            selectable: false,
            children: [...own, ...below],
          },
        ];
      });
    return walk(typeTree(types.data ?? []));
  }, [products.data, current.data, types.data, locale]);
  // No products at all (not merely none matching a search): an empty picker would leave the
  // person stuck, so the form says where products come from (QA10-P4-38), with a link for an
  // admin who may open the asset catalogue (its configure right, as the setup map asks).
  const noProducts =
    searched === '' &&
    products.data !== undefined &&
    products.data.pages.every((p) => p.items.length === 0) &&
    current.data === undefined;
  const mayConfigure = access.can('config.assets') || access.can('settings.manage');
  const vendorChoices = (vendors.data?.pages.flatMap((p) => p.items) ?? [])
    .filter((v) => v.is_active || v.id === draft.vendor_id)
    .map((v) => ({ value: v.id, label: v.name }));
  const set = (patch: Partial<AssetDraft>) => {
    onChange({ ...draft, ...patch });
  };
  const text = (field: 'tag' | 'serial_number' | 'barcode' | 'location', max: number) => (
    <Form.Item label={t(`assets.record.${field}`)} htmlFor={`asset-${field}`}>
      <Input
        id={`asset-${field}`}
        dir={field === 'location' ? 'auto' : 'ltr'}
        count={lengthLimit(max)}
        placeholder={field === 'tag' && creating ? t('assets.record.tag_auto') : undefined}
        value={draft[field]}
        onChange={(event) => {
          set({ [field]: event.target.value });
        }}
        data-testid={`asset-${field}`}
      />
    </Form.Item>
  );
  const amount = (field: 'purchase_price' | 'purchase_tax') => (
    <Form.Item label={t(`assets.record.${field}`)} htmlFor={`asset-${field}`}>
      <InputNumber<string>
        id={`asset-${field}`}
        stringMode
        min="0"
        step="0.01"
        precision={2}
        value={draft[field]}
        onChange={(value) => {
          set({ [field]: value === '' ? null : value });
        }}
        style={{ width: 160 }}
        data-testid={`asset-${field}`}
      />
    </Form.Item>
  );
  const day = (field: 'acquired_on' | 'warranty_expires_on') => (
    <Form.Item label={t(`assets.record.${field}`)} htmlFor={`asset-${field}`}>
      <DatePicker
        id={`asset-${field}`}
        value={draft[field] === null ? null : dayjs(draft[field])}
        format={pickerFormat(dates, false)}
        onChange={(value: Dayjs | null) => {
          // Cleared: antd passes null although its types say otherwise.
          set({ [field]: value?.format('YYYY-MM-DD') ?? null });
        }}
        data-testid={`asset-${field}`}
      />
    </Form.Item>
  );
  return (
    <Form layout="vertical">
      <Form.Item label={t('assets.record.name')} htmlFor="asset-name" required>
        <Input
          id="asset-name"
          dir="auto"
          count={lengthLimit(200)}
          value={draft.name}
          onChange={(event) => {
            set({ name: event.target.value });
          }}
          data-testid="asset-name"
        />
      </Form.Item>
      <Form.Item
        label={t('assets.record.product')}
        htmlFor="asset-product"
        required
        extra={
          noProducts ? (
            <span data-testid="asset-products-none">
              {t('assets.record.products_none_hint')}{' '}
              {mayConfigure && (
                <Link to="/admin/assets?tab=products" data-testid="asset-products-open">
                  {t('assets.record.products_open')}
                </Link>
              )}
            </span>
          ) : undefined
        }
      >
        <TreeSelect
          id="asset-product"
          aria-label={t('assets.record.product')}
          showSearch
          searchValue={productSearch}
          onSearch={setProductSearch}
          filterTreeNode={false}
          treeDefaultExpandAll
          loading={products.isFetching}
          notFoundContent={t('assets.record.no_products')}
          onPopupScroll={(event) => {
            const box = event.currentTarget;
            if (box.scrollTop + box.clientHeight >= box.scrollHeight - 24 && products.hasNextPage) {
              void products.fetchNextPage();
            }
          }}
          value={draft.product_id === '' ? undefined : draft.product_id}
          treeData={productChoices}
          onChange={(id: string) => {
            set({ product_id: id });
          }}
          data-testid="asset-product"
        />
      </Form.Item>
      <Flex gap={16} wrap>
        {text('tag', 120)}
        {text('serial_number', 120)}
        {text('barcode', 120)}
      </Flex>
      <Form.Item label={t('assets.record.vendor')} htmlFor="asset-vendor">
        <Select
          id="asset-vendor"
          aria-label={t('assets.record.vendor')}
          allowClear
          showSearch
          optionFilterProp="label"
          value={draft.vendor_id ?? undefined}
          options={vendorChoices}
          onChange={(id: string | undefined) => {
            set({ vendor_id: id ?? null });
          }}
          data-testid="asset-vendor"
        />
      </Form.Item>
      <Flex gap={16} wrap>
        {amount('purchase_price')}
        {amount('purchase_tax')}
        <Form.Item label={t('assets.admin.currency')} htmlFor="asset-currency">
          <Input
            id="asset-currency"
            dir="ltr"
            count={lengthLimit(3)}
            value={draft.currency}
            onChange={(event) => {
              set({ currency: event.target.value.toUpperCase() });
            }}
            style={{ width: 96 }}
          />
        </Form.Item>
      </Flex>
      <Flex gap={16} wrap>
        {day('acquired_on')}
        {day('warranty_expires_on')}
      </Flex>
      {text('location', 200)}
      <Form.Item label={t('assets.admin.description')} htmlFor="asset-description">
        <Input.TextArea
          id="asset-description"
          dir="auto"
          rows={3}
          count={lengthLimit(2000)}
          value={draft.description}
          onChange={(event) => {
            set({ description: event.target.value });
          }}
        />
      </Form.Item>
      {customFields.map((field) => {
        const id = `asset-custom-${field.key}`;
        return (
          <Form.Item
            key={field.key}
            label={fieldName(field, locale)}
            htmlFor={id}
            required={field.validation.required}
          >
            <CustomFieldControl
              id={id}
              field={field}
              value={draft.custom[field.key] ?? null}
              onChange={(next) => {
                set({ custom: { ...draft.custom, [field.key]: next } });
              }}
              testId={id}
              ariaLabel={fieldName(field, locale)}
            />
          </Form.Item>
        );
      })}
    </Form>
  );
}
