import { ReloadOutlined, RobotOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Flex, Skeleton, Typography } from 'antd';
import { useState } from 'react';

import { isApiError, useAiSettings, useAiSummary, useRefreshAiSummary } from '@supportx/api-client';
import {
  describeError,
  markHandled,
  reportError,
  ToneTag,
  useDateTime,
  useLabel,
} from '@supportx/ui';

// The conversation summary at the top of the record's panel (WP-038, REQ-INC-137): made on
// request through the AI gateway, kept until a newer reply or note makes it stale (live, from
// the record channel). Shown only while the feature is on for the tenant; the answer is marked
// as AI-written, with the model and the time. A refusal (nothing to summarise yet, the plan, the
// switch) is said in the card itself, where the person clicked (QA9-F-01); failures still report.

export const SUMMARY_FEATURE = 'conversation_summary';

export function SummaryCard({ recordId }: { recordId: string }) {
  const t = useLabel();
  const { relative, formatExact } = useDateTime();
  const settings = useAiSettings(true, true); // unreadable: the card stays hidden, no toast
  const on = settings.data?.features.find((f) => f.code === SUMMARY_FEATURE)?.enabled === true;
  const summary = useAiSummary('incident', recordId, on);
  const refresh = useRefreshAiSummary('incident', recordId);
  const [refused, setRefused] = useState<string | null>(null);
  if (!on) return null;
  const data = summary.data;
  const made = data?.summary !== null && data?.summary !== undefined;
  const make = () => {
    setRefused(null);
    refresh.mutate(undefined, {
      onError: (error) => {
        if (isApiError(error) && error.isRefusal) {
          markHandled(error);
          const { title, detail } = describeError(error, t);
          setRefused(detail ?? title);
          return;
        }
        reportError(error);
      },
    });
  };
  // Nothing summarised yet: one quiet line with its button, not an empty card (D-155).
  if (!summary.isPending && !made && refused === null) {
    return (
      <Flex align="center" gap={8} wrap data-testid="ai-summary" data-collapsed="true">
        <RobotOutlined aria-hidden />
        <Typography.Text type="secondary" data-testid="ai-summary-empty">
          {t('ai.summary.empty')}
        </Typography.Text>
        <Button
          size="small"
          type="link"
          loading={refresh.isPending}
          onClick={make}
          data-testid="ai-summary-refresh"
        >
          {t('ai.summary.make')}
        </Button>
      </Flex>
    );
  }
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
          onClick={make}
          data-testid="ai-summary-refresh"
        >
          {t(made ? 'ai.summary.refresh' : 'ai.summary.make')}
        </Button>
      }
    >
      {refused !== null && (
        <Alert
          type="info"
          showIcon
          message={refused}
          style={{ marginBottom: 8 }}
          data-testid="ai-summary-refused"
        />
      )}
      {summary.isPending ? (
        <Skeleton active paragraph={{ rows: 2 }} title={false} />
      ) : made ? (
        <Flex vertical gap={8}>
          <Flex gap={4} wrap>
            {data.stale && (
              <ToneTag tone="warning" testId="ai-summary-stale">
                {t('ai.summary.stale')}
              </ToneTag>
            )}
            {data.includes_private && (
              <ToneTag tone="default">{t('ai.summary.includes_private')}</ToneTag>
            )}
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
