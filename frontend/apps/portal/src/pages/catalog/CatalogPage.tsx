import { Breadcrumb, Card, Empty, Flex, Input, Skeleton, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';

import {
  useCatalogCategories,
  useCatalogItemList,
  useCatalogSearch,
  type CatalogCategory,
} from '@supportx/api-client';
import { textIn, useAppearance, useLabel } from '@supportx/ui';

import { Grid } from './cards';

/**
 * The catalog for requesters (WP-031, REQ-CAT-001, -027, -028): search across every language,
 * the featured items, then the categories, each with its subcategories and items. Only what the
 * requester may request is ever listed: the API decides (published, open to everyone, not in a
 * disabled category). Live: a change an admin publishes arrives without a refresh.
 */
export function CatalogPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const [params, setParams] = useSearchParams();
  const categoryId = params.get('category');
  const [search, setSearch] = useState('');
  const categories = useCatalogCategories();
  const listed = useCatalogItemList({ category_id: categoryId ?? undefined });
  const featured = useCatalogItemList({ featured: true }, categoryId === null);
  const found = useCatalogSearch(search);
  const all = useMemo(() => categories.data ?? [], [categories.data]);
  const byId = useMemo(() => new Map(all.map((c) => [c.id, c])), [all]);
  const current = categoryId === null ? undefined : byId.get(categoryId);
  const children = all
    .filter(
      (c) =>
        (c.parent_id ?? null) === (categoryId ?? null) ||
        (categoryId === null && c.parent_id !== null && !byId.has(c.parent_id)),
    )
    .sort((a, b) => a.sort_order - b.sort_order);
  const trail: CatalogCategory[] = [];
  for (
    let c = current;
    c !== undefined;
    c = c.parent_id === null ? undefined : byId.get(c.parent_id)
  ) {
    trail.unshift(c);
    if (trail.length > 4) break;
  }
  const open = (id: string | null) => {
    setSearch('');
    setParams(id === null ? {} : { category: id });
  };
  const searching = search.trim() !== '';
  return (
    <Flex vertical gap={16}>
      <Typography.Title level={1} style={{ margin: 0 }}>
        {t('nav.catalog')}
      </Typography.Title>
      <Input.Search
        size="large"
        allowClear
        placeholder={t('portal.catalog.search')}
        aria-label={t('portal.catalog.search')}
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
        }}
        data-testid="portal-cat-search"
      />
      {searching ? (
        found.isLoading ? (
          <Skeleton active />
        ) : (found.data ?? []).length === 0 ? (
          <Empty description={t('portal.catalog.no_match')} data-testid="portal-cat-no-match" />
        ) : (
          <Grid items={found.data ?? []} />
        )
      ) : (
        <>
          {trail.length > 0 && (
            <Breadcrumb
              items={[
                {
                  title: (
                    <a
                      href="#"
                      onClick={(event) => {
                        event.preventDefault();
                        open(null);
                      }}
                    >
                      {t('nav.catalog')}
                    </a>
                  ),
                },
                ...trail.map((c) => ({
                  title:
                    c.id === categoryId ? (
                      textIn(c.names, locale)
                    ) : (
                      <a
                        href="#"
                        onClick={(event) => {
                          event.preventDefault();
                          open(c.id);
                        }}
                      >
                        {textIn(c.names, locale)}
                      </a>
                    ),
                })),
              ]}
            />
          )}
          {categoryId === null && (featured.data ?? []).length > 0 && (
            <section aria-labelledby="portal-cat-featured">
              <Typography.Title level={2} id="portal-cat-featured" style={{ fontSize: 18 }}>
                {t('portal.catalog.featured')}
              </Typography.Title>
              <Grid items={featured.data ?? []} />
            </section>
          )}
          {children.length > 0 && (
            <section aria-labelledby="portal-cat-categories">
              <Typography.Title level={2} id="portal-cat-categories" style={{ fontSize: 18 }}>
                {t(
                  categoryId === null
                    ? 'portal.catalog.categories'
                    : 'portal.catalog.subcategories',
                )}
              </Typography.Title>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
                  gap: 12,
                }}
              >
                {children.map((c) => (
                  <Card
                    key={c.id}
                    size="small"
                    hoverable
                    role="link"
                    tabIndex={0}
                    onClick={() => {
                      open(c.id);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        open(c.id);
                      }
                    }}
                    data-testid={`portal-cat-category-${c.id}`}
                  >
                    <Typography.Text strong>{textIn(c.names, locale)}</Typography.Text>
                  </Card>
                ))}
              </div>
            </section>
          )}
          {categoryId !== null &&
            (listed.isLoading ? (
              <Skeleton active />
            ) : (listed.data ?? []).length === 0 && children.length === 0 ? (
              <Empty description={t('portal.catalog.empty_category')} />
            ) : (
              <Grid items={listed.data ?? []} />
            ))}
          {categoryId === null && all.length === 0 && !categories.isLoading && (
            <Empty description={t('portal.catalog.empty')} data-testid="portal-cat-empty" />
          )}
        </>
      )}
    </Flex>
  );
}
