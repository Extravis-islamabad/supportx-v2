import { Button, List, Space, Tag, Typography } from 'antd';
import { Link } from 'react-router';

import { useKbArticleLinks, useUnlinkKbArticle, type KbArticle } from '@supportx/api-client';
import { EmptyText, reportError, useLabel } from '@supportx/ui';

/**
 * The article's Links tab (REQ-KB-064, D-121): the records it is linked to that the reader may
 * open (ID, subject, status, how it was linked), and how many others. Refetched live by the page
 * on the article's channel (`knowledge.link.*`).
 */
export function ArticleLinks({ article }: { article: KbArticle }) {
  const t = useLabel();
  const links = useKbArticleLinks(article.id);
  const unlink = useUnlinkKbArticle();
  const items = links.data?.items ?? [];
  const restricted = links.data?.restricted ?? 0;
  if (links.data !== undefined && items.length === 0 && restricted === 0) {
    return <EmptyText>{t('knowledge.links.empty')}</EmptyText>;
  }
  return (
    <Space direction="vertical" style={{ width: '100%' }} data-testid="kb-links">
      <List
        size="small"
        loading={links.isPending}
        dataSource={items}
        renderItem={(item) => (
          <List.Item
            key={item.link_id}
            data-testid={`kb-link-${item.display_id}`}
            actions={
              article.can_edit
                ? [
                    <Button
                      key="unlink"
                      size="small"
                      type="link"
                      onClick={() => {
                        unlink.mutate(
                          {
                            articleId: article.id,
                            linkId: item.link_id,
                            recordType: item.record_type,
                            recordId: item.record_id,
                          },
                          { onError: reportError },
                        );
                      }}
                    >
                      {t('knowledge.card.unlink')}
                    </Button>,
                  ]
                : []
            }
          >
            <Space wrap>
              <Link to={`/incidents/${item.record_id}`}>{item.display_id}</Link>
              <Typography.Text dir="auto">{item.subject}</Typography.Text>
              <Tag>{t(`status_category.${item.status_category}`)}</Tag>
              <Tag>{t(`kb_link_source.${item.source}`)}</Tag>
            </Space>
          </List.Item>
        )}
      />
      {restricted > 0 && (
        <Typography.Text type="secondary" data-testid="kb-links-restricted">
          {t('knowledge.links.restricted', { count: restricted })}
        </Typography.Text>
      )}
    </Space>
  );
}
