import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import { Card, Flex, Tag, Typography } from 'antd';
import { Link } from 'react-router';

import type { CatalogCategory, CatalogItem } from '@supportx/api-client';
import { CatalogIcon, textIn, useAppearance, useLabel } from '@supportx/ui';

import { entryPath } from './entries';

/** One item as a card: its icon, name, summary, and "needs approval" when it has an approval stage. */
export function ItemCard({ item }: { item: CatalogItem }) {
  const t = useLabel();
  const { locale, direction } = useAppearance();
  // Not when the tenant hides approvals from requesters (REQ-SR-024 AC3).
  const approval = item.requesters_see_approval && (item.approval?.approvers ?? []).length > 0;
  return (
    <Link
      to={entryPath(item)}
      data-testid={`portal-cat-item-${item.id}`}
      style={{ display: 'block' }}
    >
      <Card size="small" hoverable style={{ height: '100%' }}>
        <Flex align="center" gap={12}>
          <CatalogIcon code={item.icon} />
          <Flex vertical gap={2} style={{ minWidth: 0, flex: 1 }}>
            <Typography.Text strong>{textIn(item.names, locale)}</Typography.Text>
            <Typography.Text type="secondary" ellipsis>
              {textIn(item.summaries, locale)}
            </Typography.Text>
            {approval && (
              <span>
                <Tag data-testid={`portal-cat-needs-approval-${item.id}`}>
                  {t('portal.catalog.needs_approval')}
                </Tag>
              </span>
            )}
          </Flex>
          {direction === 'rtl' ? <LeftOutlined aria-hidden /> : <RightOutlined aria-hidden />}
        </Flex>
      </Card>
    </Link>
  );
}

export function Grid({ items }: { items: CatalogItem[] }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
        gap: 12,
      }}
    >
      {items.map((item) => (
        <ItemCard key={item.id} item={item} />
      ))}
    </div>
  );
}

/**
 * A category as a tile (QA6-PRT-01): its icon, name, description and how many items it holds
 * (its subcategories' included). Opens the category.
 */
export function CategoryTile({
  category,
  count,
  onOpen,
}: {
  category: CatalogCategory;
  count: number;
  onOpen: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const description = textIn(category.descriptions, locale);
  return (
    <Card
      size="small"
      hoverable
      role="link"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onOpen();
        }
      }}
      style={{ height: '100%' }}
      data-testid={`portal-cat-category-${category.id}`}
    >
      <Flex align="flex-start" gap={12}>
        <CatalogIcon code={category.icon} />
        <Flex vertical gap={2} style={{ minWidth: 0 }}>
          <Typography.Text strong>{textIn(category.names, locale)}</Typography.Text>
          {description !== '' && (
            <Typography.Text type="secondary" ellipsis>
              {description}
            </Typography.Text>
          )}
          <Typography.Text type="secondary" data-testid={`portal-cat-count-${category.id}`}>
            {t('portal.catalog.items', { count })}
          </Typography.Text>
        </Flex>
      </Flex>
    </Card>
  );
}
