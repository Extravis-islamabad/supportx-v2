import { ReloadOutlined, RobotOutlined } from '@ant-design/icons';
import { Button, Card, Flex, Skeleton, Tag, Typography } from 'antd';

import { useAiSettings, useAiSummary, useRefreshAiSummary } from '@supportx/api-client';
import { reportError, useDateTime, useLabel } from '@supportx/ui';

// The conversation summary at the top of the record's panel (WP-038, REQ-INC-137): made on
// request through the AI gateway, kept until a newer reply or note makes it stale (live, from
// the record channel). Shown only while the feature is on for the tenant; the answer is marked
// as AI-written, with the model and the time.

export const SUMMARY_FEATURE = 'conversation_summary';

export function SummaryCard({ recordId }: { recordId: string }) {
  const t = useLabel();
  const { relative, formatExact } = useDateTime();
  const settings = useAiSettings(true, true); // unreadable: the card stays hidden, no toast
  const on = settings.data?.features.find((f) => f.code === SUMMARY_FEATURE)?.enabled === true;
  const summary = useAiSummary('incident', recordId, on);
  const refresh = useRefreshAiSummary('incident', recordId);
  if (!on) return null;
  const data = summary.data;
  const made = data?.summary !== null && data?.summary !== undefined;
  return (
    <Card
      size="small"
      data-testid="ai-summary"
      title={
        <Flex align="center" gap={6}>
          <RobotOutlined aria-hidden />
          {t('ai.summary.title')}
        </Flex>
      }
      extra={
        <Button
          size="small"
          icon={<ReloadOutlined />}
          loading={refresh.isPending}
          onClick={() => {
            refresh.mutate(undefined, { onError: reportError });
          }}
          data-testid="ai-summary-refresh"
        >
          {t(made ? 'ai.summary.refresh' : 'ai.summary.make')}
        </Button>
      }
    >
      {summary.isPending ? (
        <Skeleton active paragraph={{ rows: 2 }} title={false} />
      ) : made ? (
        <Flex vertical gap={8}>
          <Flex gap={4} wrap>
            {data.stale && (
              <Tag color="warning" data-testid="ai-summary-stale">
                {t('ai.summary.stale')}
              </Tag>
            )}
            {data.includes_private && <Tag>{t('ai.summary.includes_private')}</Tag>}
          </Flex>
          <Typography.Paragraph
            dir="auto"
            style={{ whiteSpace: 'pre-line', marginBottom: 0 }}
            data-testid="ai-summary-text"
          >
            {data.summary}
          </Typography.Paragraph>
          <Typography.Text
            type="secondary"
            style={{ fontSize: 12 }}
            title={formatExact(data.made_at)}
          >
            {t('ai.summary.made_by', { model: data.model ?? '', when: relative(data.made_at) })}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t('ai.summary.check')}
          </Typography.Text>
        </Flex>
      ) : (
        <Typography.Text type="secondary" data-testid="ai-summary-empty">
          {t('ai.summary.empty')}
        </Typography.Text>
      )}
    </Card>
  );
}
