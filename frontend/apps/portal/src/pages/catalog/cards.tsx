import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import { Card, Flex, Tag, Typography } from 'antd';
import { Link } from 'react-router';

import type { CatalogItem } from '@supportx/api-client';
import { textIn, useAppearance, useLabel } from '@supportx/ui';

import { entryPath } from './entries';

/** One item as a card: name, summary, and "needs approval" when it has an approval stage. */
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
        <Flex align="center" justify="space-between" gap={8}>
          <Flex vertical gap={2} style={{ minWidth: 0 }}>
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
