import {
  Alert,
  App,
  Card,
  Flex,
  Form,
  InputNumber,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Switch,
  Table,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  useConsumables,
  useStockRuleActions,
  useStockRules,
  useUser,
  type AssetProductType,
  type AssetStockRule,
} from '@supportx/api-client';
import { EmptyText, useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { okFooter } from '../../assets/dialogOk';
import { useSiteNames } from '../../assets/live';
import { problemText } from '../../assets/problemText';
import { plainQuantity } from '../../assets/quantity';
import { SitePicker, UserPicker } from '../../incidents/pickers';
import { nameOf } from './shared';

type Target = 'type' | 'product';

interface Draft {
  target: Target;
  typeId: string | null;
  productId: string | null;
  siteId: string | null;
  minimum: string | null;
  people: string[];
  purchase: boolean;
  reorder: string | null;
}

const EMPTY: Draft = {
  target: 'type',
  typeId: null,
  productId: null,
  siteId: null,
  minimum: null,
  people: [],
  purchase: false,
  reorder: null,
};

function draftOf(rule: AssetStockRule): Draft {
  return {
    target: rule.product_id === null ? 'type' : 'product',
    typeId: rule.product_type_id,
    productId: rule.product_id,
    siteId: rule.site_id,
    minimum: rule.min_quantity,
    people: rule.notify_user_ids,
    purchase: rule.create_purchase_request,
    reorder: rule.reorder_quantity,
  };
}

/** Several people to tell: one picker per pick, the picked ones listed with a remove. */
function PeoplePicker({ value, onChange }: { value: string[]; onChange: (ids: string[]) => void }) {
  const t = useLabel();
  return (
    <Flex vertical gap={8}>
      <UserPicker
        value={null}
        onChange={(id) => {
          if (id !== null && !value.includes(id)) onChange([...value, id]);
        }}
        testId="stock-rule-person"
        ariaLabel={t('assets.rules.notify')}
      />
      {value.map((id) => (
        <Flex key={id} gap={8} align="center">
          <PersonChip id={id} />
          <Typography.Link
            onClick={() => {
              onChange(value.filter((p) => p !== id));
            }}
          >
            {t('assets.rules.remove')}
          </Typography.Link>
        </Flex>
      ))}
    </Flex>
  );
}

function PersonChip({ id }: { id: string }) {
  const t = useLabel();
  const user = useUser(id);
  return <bdi dir="auto">{user.data?.display_name ?? t('audit.ui.erased_person')}</bdi>;
}

function RuleDialog({
  rule,
  open,
  types,
  onClose,
}: {
  rule: AssetStockRule | undefined;
  open: boolean;
  types: AssetProductType[];
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const { create, update } = useStockRuleActions();
  const consumables = useConsumables({}, open);
  const [d, setD] = useState<Draft>(() => (rule === undefined ? EMPTY : draftOf(rule)));
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
  const done = {
    onSuccess: () => {
      void message.success(t('settings.saved'));
      close();
    },
    onError: (error: unknown) => {
      setProblem(problemText(t, error));
    },
  };
  const consumableTypes = types.filter((x) => x.kind === 'consumable');
  const why =
    d.target === 'type' && d.typeId === null
      ? t('assets.rules.type_needed')
      : d.target === 'product' && d.productId === null
        ? t('assets.rules.product_needed')
        : d.minimum === null || d.minimum === ''
          ? t('assets.rules.minimum_needed')
          : d.purchase && (d.reorder === null || d.reorder === '')
            ? t('assets.rules.reorder_needed')
            : undefined;
  return (
    <Modal
      open={open}
      title={rule === undefined ? t('assets.rules.add') : t('assets.rules.edit')}
      cancelText={t('actions.cancel')}
      onCancel={close}
      footer={okFooter({
        okText: t('actions.save'),
        loading: create.isPending || update.isPending,
        whyDisabled: why,
        testId: 'stock-rule-save',
        onOk: () => {
          if (d.minimum === null) return;
          setProblem(null);
          const shared = {
            site_id: d.siteId,
            min_quantity: d.minimum,
            notify_user_ids: d.people,
            create_purchase_request: d.purchase,
            reorder_quantity: d.purchase ? d.reorder : null,
          };
          if (rule === undefined) {
            create.mutate(
              {
                key,
                body: {
                  ...shared,
                  product_type_id: d.target === 'type' ? d.typeId : null,
                  product_id: d.target === 'product' ? d.productId : null,
                },
              },
              done,
            );
          } else {
            update.mutate({ id: rule.id, version: rule.version, body: shared }, done);
          }
        },
      })}
      destroyOnHidden
      data-testid="stock-rule-dialog"
    >
      {problem !== null && (
        <Alert type="error" showIcon message={problem} style={{ marginBottom: 12 }} />
      )}
      <Form layout="vertical" component="div">
        <Form.Item label={t('assets.rules.applies_to')}>
          <Segmented<Target>
            value={d.target}
            disabled={rule !== undefined}
            onChange={(target) => {
              edit({ target });
            }}
            options={[
              { value: 'type', label: t('assets.rules.a_type') },
              { value: 'product', label: t('assets.rules.a_product') },
            ]}
            data-testid="stock-rule-target"
          />
        </Form.Item>
        {d.target === 'type' ? (
          <Form.Item label={t('assets.admin.product_type')} required>
            <Select
              value={d.typeId}
              disabled={rule !== undefined}
              aria-label={t('assets.admin.product_type')}
              onChange={(typeId: string) => {
                edit({ typeId });
              }}
              options={consumableTypes.map((x) => ({
                value: x.id,
                label: nameOf(x.names, locale),
              }))}
              data-testid="stock-rule-type"
            />
          </Form.Item>
        ) : (
          <Form.Item label={t('assets.stock.product')} required>
            <Select
              showSearch
              optionFilterProp="label"
              value={d.productId}
              disabled={rule !== undefined}
              aria-label={t('assets.stock.product')}
              onChange={(productId: string) => {
                edit({ productId });
              }}
              options={(consumables.data ?? []).map((c) => ({
                value: c.product_id,
                label: c.product_name,
              }))}
              data-testid="stock-rule-product"
            />
          </Form.Item>
        )}
        <Form.Item label={t('assets.stock.site')} extra={t('assets.rules.site_help')}>
          <SitePicker
            value={d.siteId}
            onChange={(siteId) => {
              edit({ siteId });
            }}
            ariaLabel={t('assets.stock.site')}
            testId="stock-rule-site"
          />
        </Form.Item>
        <Form.Item
          label={t('assets.stock.minimum')}
          required
          extra={t('assets.rules.minimum_help')}
          htmlFor="stock-rule-minimum"
        >
          <InputNumber<string>
            id="stock-rule-minimum"
            stringMode
            min="0"
            value={d.minimum}
            onChange={(minimum) => {
              edit({ minimum });
            }}
            data-testid="stock-rule-minimum"
          />
        </Form.Item>
        <Form.Item label={t('assets.rules.notify')}>
          <PeoplePicker
            value={d.people}
            onChange={(people) => {
              edit({ people });
            }}
          />
        </Form.Item>
        <Form.Item
          label={t('assets.rules.purchase')}
          extra={t('assets.rules.purchase_help')}
          htmlFor="stock-rule-purchase"
        >
          <Switch
            id="stock-rule-purchase"
            checked={d.purchase}
            onChange={(purchase) => {
              edit({ purchase });
            }}
          />
        </Form.Item>
        {d.purchase && (
          <Form.Item label={t('assets.rules.reorder')} required htmlFor="stock-rule-reorder">
            <InputNumber<string>
              id="stock-rule-reorder"
              stringMode
              min="0"
              value={d.reorder}
              onChange={(reorder) => {
                edit({ reorder });
              }}
            />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}

/**
 * Minimum stock (WP-049b s1; REQ-AST-035): a minimum per consumable type or product, per site or
 * every site, and who hears when stock falls to it (once, until it rises above again).
 */
export function StockRulesTab({ types }: { types: AssetProductType[] }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const rules = useStockRules();
  const consumables = useConsumables({});
  const { remove } = useStockRuleActions();
  const siteName = useSiteNames();
  const [editing, setEditing] = useState<AssetStockRule | 'new'>();
  const products = new Map((consumables.data ?? []).map((c) => [c.product_id, c.product_name]));
  const typeName = (id: string | null) => {
    const found = types.find((x) => x.id === id);
    return found === undefined ? '' : nameOf(found.names, locale);
  };
  return (
    <Card
      title={t('assets.rules.title')}
      extra={
        <WriteButton
          type="primary"
          onClick={() => {
            setEditing('new');
          }}
          data-testid="stock-rule-add"
        >
          {t('assets.rules.add')}
        </WriteButton>
      }
      data-testid="stock-rules"
    >
      <Typography.Paragraph type="secondary">{t('assets.rules.help')}</Typography.Paragraph>
      <Table<AssetStockRule>
        size="small"
        rowKey="id"
        loading={rules.isPending}
        dataSource={rules.data ?? []}
        pagination={false}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: <EmptyText>{t('assets.rules.none')}</EmptyText> }}
        columns={[
          {
            key: 'target',
            title: t('assets.rules.applies_to'),
            render: (_, r) => (
              <bdi dir="auto">
                {r.product_id === null
                  ? typeName(r.product_type_id)
                  : (products.get(r.product_id) ?? '')}
              </bdi>
            ),
          },
          {
            key: 'site',
            title: t('assets.stock.site'),
            render: (_, r) =>
              r.site_id === null ? (
                t('assets.rules.every_site')
              ) : (
                <bdi dir="auto">{siteName(r.site_id)}</bdi>
              ),
          },
          {
            key: 'minimum',
            title: t('assets.stock.minimum'),
            align: 'end',
            render: (_, r) => plainQuantity(r.min_quantity),
          },
          {
            key: 'notify',
            title: t('assets.rules.notify'),
            render: (_, r) => t('assets.rules.people', { count: r.notify_user_ids.length }),
          },
          {
            key: 'actions',
            title: t('assets.admin.actions'),
            render: (_, r) => (
              <Flex gap={4}>
                <WriteButton
                  size="small"
                  onClick={() => {
                    setEditing(r);
                  }}
                  data-testid={`stock-rule-edit-${r.id}`}
                >
                  {t('actions.edit')}
                </WriteButton>
                <Popconfirm
                  title={t('assets.rules.remove_confirm')}
                  okText={t('assets.rules.remove')}
                  cancelText={t('actions.cancel')}
                  onConfirm={() => {
                    remove.mutate({ id: r.id, version: r.version });
                  }}
                >
                  <WriteButton size="small" danger data-testid={`stock-rule-remove-${r.id}`}>
                    {t('assets.rules.remove')}
                  </WriteButton>
                </Popconfirm>
              </Flex>
            ),
          },
        ]}
        data-testid="stock-rules-table"
      />
      {editing !== undefined && (
        <RuleDialog
          rule={editing === 'new' ? undefined : editing}
          open
          types={types}
          onClose={() => {
            setEditing(undefined);
          }}
        />
      )}
    </Card>
  );
}
