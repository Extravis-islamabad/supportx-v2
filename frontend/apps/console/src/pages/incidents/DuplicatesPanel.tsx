import { CopyOutlined } from '@ant-design/icons';
import { Card, Flex, List, Typography } from 'antd';
import { Link } from 'react-router';

import { useIncidentCatalogue, type PossibleDuplicates } from '@supportx/api-client';
import { ToneTag, useAppearance, useLabel } from '@supportx/ui';

import { statusLabel } from './labels';

// Possible duplicates beside the new-incident form (WP-038, REQ-INC-022, D-134): open incidents
// you may see that look like the one being written, best first. With AI on they were found by
// meaning, with AI off by subject; the card says which. Opening one never loses the draft (the
// form keeps it). Nothing shows until there is something to show.

export function DuplicatesPanel({ found }: { found: PossibleDuplicates | undefined }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const catalogue = useIncidentCatalogue();
  if (found === undefined || found.items.length === 0) return null;
  return (
    <Card
      size="small"
      data-testid="inc-duplicates"
      title={
        <Flex align="center" gap={6}>
          <CopyOutlined aria-hidden />
          {t('incidents.duplicates.title')}
        </Flex>
      }
    >
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        {t(`duplicate_method.${found.method}`)}
      </Typography.Paragraph>
      <List
        size="small"
        dataSource={found.items}
        renderItem={(entry) => (
          <List.Item data-testid={`inc-duplicate-${entry.item.display_id}`}>
            <Flex vertical gap={2} style={{ minWidth: 0 }}>
              <Link to={`/incidents/${entry.item.id}`} target="_blank" rel="noopener">
                <Typography.Text strong>
                  <bdi dir="ltr">{entry.item.display_id}</bdi>
                </Typography.Text>{' '}
                <bdi dir="auto">{entry.item.subject}</bdi>
              </Link>
              <Flex gap={4} wrap>
                <ToneTag tone="default">
                  {statusLabel(t, catalogue.data, entry.item.status, locale)}
                </ToneTag>
                {entry.reasons.map((reason) => (
                  <ToneTag key={reason} tone="info">
                    {t(`duplicate_reason.${reason}`)}
                  </ToneTag>
                ))}
              </Flex>
            </Flex>
          </List.Item>
        )}
      />
    </Card>
  );
}
