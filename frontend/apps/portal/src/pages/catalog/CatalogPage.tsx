import { Breadcrumb, Empty, Flex, Input, Skeleton, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';

import {
  useCatalogCategories,
  useCatalogItemList,
  useCatalogSearch,
  usePopularCatalogItems,
  type CatalogCategory,
} from '@supportx/api-client';
import { textIn, useAppearance, useLabel } from '@supportx/ui';

import { CategoryTile, Grid } from './cards';

/**
 * The catalog for requesters (WP-031, REQ-CAT-001, -027, -028): search across every language,
 * the featured items (or, while none is featured, the most requested), then the categories as
 * tiles with their icon and item count (QA6-PRT-01), each with its subcategories and items. Only what the
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
  const noneFeatured = featured.isSuccess && featured.data.length === 0;
  const popular = usePopularCatalogItems(categoryId === null && noneFeatured);
  const found = useCatalogSearch(search);
  const all = useMemo(() => categories.data ?? [], [categories.data]);
  const byId = useMemo(() => new Map(all.map((c) => [c.id, c])), [all]);
  // Every item the viewer may request (the top level's own list, shared through its query
  // key), each counted in its category and every category above it.
  const everything = useCatalogItemList({});
  const counts = useMemo(() => {
    const found = new Map<string, number>();
    for (const item of everything.data ?? []) {
      let at = item.category_id === null ? undefined : byId.get(item.category_id);
      for (let depth = 0; at !== undefined && depth < 6; depth += 1) {
        found.set(at.id, (found.get(at.id) ?? 0) + 1);
        at = at.parent_id === null ? undefined : byId.get(at.parent_id);
      }
    }
    return found;
  }, [everything.data, byId]);
  const shown = noneFeatured ? (popular.data ?? []) : (featured.data ?? []);
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
          {categoryId === null && shown.length > 0 && (
            <section aria-labelledby="portal-cat-featured">
              <Typography.Title level={2} id="portal-cat-featured" style={{ fontSize: 18 }}>
                {t('portal.catalog.featured')}
              </Typography.Title>
              <Grid items={shown} />
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
                  gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
                  gap: 12,
                }}
              >
                {children.map((c) => (
                  <CategoryTile
                    key={c.id}
                    category={c}
                    count={counts.get(c.id) ?? 0}
                    onOpen={() => {
                      open(c.id);
                    }}
                  />
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
