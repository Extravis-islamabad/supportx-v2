import { SearchOutlined } from '@ant-design/icons';
import { Button, Flex, Select, Tooltip, Typography } from 'antd';
import { useMemo, useState } from 'react';

import { useIncidentCategories, type IncidentCategory } from '@supportx/api-client';
import { useAppearance, useLabel } from '@supportx/ui';

import { categoryLabel, categoryPath } from './labels';

const LEVELS = ['category', 'subcategory', 'item'] as const;

/**
 * Category › subcategory › item as three dependent pickers (REQ-INC-006). The value is the
 * deepest node chosen. Each picker offers only the children of the one before (AC1); changing
 * a level clears the levels below and says so (AC2); retired nodes are not offered, except the
 * one the record already has, marked (AC3). "Search all levels" finds a node by name at any
 * depth (AC4).
 */
export function CategoryCascade({
  id,
  value,
  onChange,
  disabled,
  testId,
}: {
  id?: string;
  value: string | null;
  onChange: (next: string | null) => void;
  disabled?: boolean;
  testId: string;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const categories = useIncidentCategories();
  const [notice, setNotice] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const nodes = useMemo(() => categories.data ?? [], [categories.data]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const path = useMemo(() => {
    const chain: IncidentCategory[] = [];
    let current = value === null ? undefined : byId.get(value);
    while (current !== undefined) {
      chain.unshift(current);
      current = current.parent_id === null ? undefined : byId.get(current.parent_id);
    }
    return chain;
  }, [byId, value]);
  const childrenOf = (parent: string | null) => nodes.filter((n) => n.parent_id === parent);
  const label = (node: IncidentCategory) =>
    node.disabled
      ? t('categories.retired_value', { name: categoryLabel(t, node, locale) })
      : categoryLabel(t, node, locale);

  const choose = (level: number, next: string | null) => {
    const below = path.slice(level + 1);
    const changed = (path[level]?.id ?? null) !== next;
    if (changed && below.length > 0) {
      setNotice(
        t(level === 0 ? 'categories.cleared_below_category' : 'categories.cleared_below_sub', {
          name: next === null ? '' : label(byId.get(next) as IncidentCategory),
        }),
      );
    } else {
      setNotice(null);
    }
    onChange(next ?? path[level - 1]?.id ?? null);
  };

  const pickers = LEVELS.map((name, level) => {
    const parent = level === 0 ? null : (path[level - 1]?.id ?? undefined);
    const options =
      parent === undefined
        ? []
        : childrenOf(parent)
            .filter((n) => !n.disabled || n.id === path[level]?.id)
            .map((n) => ({ value: n.id, label: label(n) }));
    const off = disabled === true || parent === undefined || options.length === 0;
    return (
      <Select
        key={name}
        id={level === 0 ? id : undefined}
        aria-label={t(`categories.level.${name}`)}
        placeholder={
          parent !== undefined && options.length === 0 && level > 0
            ? t('categories.none_below')
            : t(`categories.level.${name}`)
        }
        allowClear
        showSearch
        optionFilterProp="label"
        disabled={off}
        value={path[level]?.id}
        onChange={(next: string | undefined) => {
          choose(level, next ?? null);
        }}
        options={options}
        style={{ flex: '1 1 140px', minWidth: 0 }}
        data-testid={`${testId}-${name}`}
      />
    );
  });

  return (
    <Flex vertical gap={4} style={{ width: '100%' }} data-testid={testId}>
      {searching ? (
        <Flex gap={8}>
          <Select
            autoFocus
            showSearch
            defaultOpen
            aria-label={t('categories.search_all')}
            placeholder={t('categories.search_all')}
            optionFilterProp="label"
            style={{ flex: 1, minWidth: 0 }}
            options={nodes
              .filter((n) => !n.disabled)
              .map((n) => ({ value: n.id, label: categoryPath(t, nodes, n.id, locale) }))}
            onChange={(next: string) => {
              setNotice(null);
              onChange(next);
              setSearching(false);
            }}
            onBlur={() => {
              setSearching(false);
            }}
            data-testid={`${testId}-search`}
          />
        </Flex>
      ) : (
        <Flex gap={8} wrap align="center">
          {pickers}
          <Tooltip title={t('categories.search_all')}>
            <Button
              icon={<SearchOutlined />}
              aria-label={t('categories.search_all')}
              disabled={disabled}
              onClick={() => {
                setSearching(true);
              }}
              data-testid={`${testId}-search-open`}
            />
          </Tooltip>
        </Flex>
      )}
      {notice !== null && (
        <Typography.Text type="secondary" role="status" data-testid={`${testId}-notice`}>
          {notice}
        </Typography.Text>
      )}
    </Flex>
  );
}
