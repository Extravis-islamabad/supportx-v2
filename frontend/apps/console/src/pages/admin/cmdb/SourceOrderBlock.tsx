import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { App, Button, Flex, Select, Space, Tag, Typography } from 'antd';
import { useState } from 'react';

import {
  useCustomFields,
  useSourcePrecedence,
  useUpdateSourcePrecedence,
  type AttributeSourceCode,
} from '@supportx/api-client';
import {
  FormProblem,
  SettingsCard,
  WriteButton,
  useAppearance,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

import { fieldName } from '../../customFields/values';
import { SyncRulesLink } from './SyncRulesPage';

type Order = AttributeSourceCode[];

function move(order: Order, index: number, by: -1 | 1): Order {
  const next = [...order];
  const [item] = next.splice(index, 1);
  if (item !== undefined) next.splice(index + by, 0, item);
  return next;
}

/** One order of sources, strongest first, moved with buttons (keyboard and screen readers). */
function OrderEditor({
  order,
  lockFirst,
  onChange,
  testId,
}: {
  order: Order;
  lockFirst: boolean;
  onChange: (next: Order) => void;
  testId: string;
}) {
  const t = useLabel();
  return (
    <Flex gap={6} wrap align="center" data-testid={testId}>
      {order.map((source, index) => {
        const locked = lockFirst && index === 0;
        const name = t(`cmdb_attribute_source.${source}`);
        return (
          <Tag key={source} style={{ marginInlineEnd: 0 }} data-testid={`${testId}-${source}`}>
            <Space size={2}>
              <Typography.Text>{`${String(index + 1)}. ${name}`}</Typography.Text>
              {!locked && (
                <>
                  <Button
                    size="small"
                    type="text"
                    icon={<ArrowUpOutlined />}
                    disabled={index === 0 || (lockFirst && index === 1)}
                    aria-label={t('cmdb.sources.move_up', { source: name })}
                    onClick={() => {
                      onChange(move(order, index, -1));
                    }}
                  />
                  <Button
                    size="small"
                    type="text"
                    icon={<ArrowDownOutlined />}
                    disabled={index === order.length - 1}
                    aria-label={t('cmdb.sources.move_down', { source: name })}
                    onClick={() => {
                      onChange(move(order, index, 1));
                    }}
                  />
                </>
              )}
            </Space>
          </Tag>
        );
      })}
    </Flex>
  );
}

/**
 * Which source wins (REQ-CMDB-016): the order for every CI attribute, with changes by hand first,
 * and an order of its own for chosen attributes (where hand may rank lower, so a sync may then
 * overwrite a hand-set value there). Saving is audited with the order before and after.
 */
export function SourceOrderBlock() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const found = useSourcePrecedence();
  const save = useUpdateSourcePrecedence();
  const custom = useCustomFields('ci');
  const problem = useFormProblem();
  const [order, setOrder] = useState<Order>([]);
  const [overrides, setOverrides] = useState<Record<string, Order>>({});
  const [dirty, setDirty] = useState(false);
  // The saved order into the editor when it loads or changes elsewhere (live), unless the person
  // has unsaved changes (adjusted during render).
  const [shown, setShown] = useState<number>();
  if (found.data !== undefined && !dirty && shown !== found.data.version) {
    setShown(found.data.version);
    setOrder(found.data.order);
    setOverrides(found.data.overrides ?? {});
  }
  const label = (attribute: string) => {
    if (!attribute.startsWith('custom.')) return t(`cmdb.field.${attribute}`);
    const field = custom.data?.find((f) => `custom.${f.key}` === attribute);
    return field === undefined ? t('cmdb.sync.removed_field') : fieldName(field, locale);
  };
  const free = (found.data?.attributes ?? []).filter((a) => overrides[a] === undefined);
  return (
    <SettingsCard
      title={t('cmdb.sources.title')}
      description={t('cmdb.sources.description')}
      testId="cmdb-sources"
    >
      <Flex vertical gap={12}>
        <FormProblem problem={problem} />
        <SyncRulesLink />
        <Typography.Text strong>{t('cmdb.sources.order')}</Typography.Text>
        <OrderEditor
          order={order}
          lockFirst
          testId="cmdb-sources-order"
          onChange={(next) => {
            setOrder(next);
            setDirty(true);
          }}
        />
        <Typography.Text strong>{t('cmdb.sources.overrides')}</Typography.Text>
        {Object.entries(overrides).map(([attribute, own]) => (
          <Flex
            key={attribute}
            gap={8}
            align="center"
            wrap
            data-testid={`cmdb-sources-override-${attribute}`}
          >
            <Typography.Text style={{ minWidth: 160 }}>
              <bdi dir="auto">{label(attribute)}</bdi>
            </Typography.Text>
            <OrderEditor
              order={own}
              lockFirst={false}
              testId={`cmdb-sources-override-order-${attribute}`}
              onChange={(next) => {
                setOverrides({ ...overrides, [attribute]: next });
                setDirty(true);
              }}
            />
            <Button
              type="text"
              icon={<DeleteOutlined />}
              aria-label={t('cmdb.sources.remove_override', { field: label(attribute) })}
              onClick={() => {
                setOverrides(
                  Object.fromEntries(Object.entries(overrides).filter(([a]) => a !== attribute)),
                );
                setDirty(true);
              }}
            />
          </Flex>
        ))}
        {free.length > 0 && (
          <Select
            style={{ maxWidth: 320 }}
            value={null}
            aria-label={t('cmdb.sources.add_override')}
            placeholder={
              <Space>
                <PlusOutlined />
                {t('cmdb.sources.add_override')}
              </Space>
            }
            onChange={(attribute: string) => {
              setOverrides({ ...overrides, [attribute]: [...order] });
              setDirty(true);
            }}
            options={free.map((a) => ({ value: a, label: label(a) }))}
            data-testid="cmdb-sources-add-override"
          />
        )}
        <div>
          <WriteButton
            type="primary"
            disabled={!dirty || found.data === undefined}
            whyDisabled={t('why.nothing_changed')}
            loading={save.isPending}
            onClick={() => {
              if (found.data === undefined) return;
              save.mutate(
                { order, overrides, version: found.data.version },
                {
                  onSuccess: () => {
                    setDirty(false);
                    void message.success(t('cmdb.sources.saved'));
                  },
                  onError: (e) => {
                    problem.show(e);
                  },
                },
              );
            }}
            data-testid="cmdb-sources-save"
          >
            {t('actions.save')}
          </WriteButton>
        </div>
      </Flex>
    </SettingsCard>
  );
}
