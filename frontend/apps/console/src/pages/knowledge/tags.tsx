import { Space } from 'antd';

import type { KbArticleRow } from '@supportx/api-client';
import { ToneTag, useLabel, type Tone } from '@supportx/ui';

const STATUS_TONES: Record<string, Tone> = {
  draft: 'default',
  in_review: 'purple',
  published: 'success',
  superseded: 'default',
  rejected: 'warning',
};

export function VersionStatusTag({ status }: { status: string }) {
  const t = useLabel();
  return (
    <ToneTag tone={STATUS_TONES[status] ?? 'default'} testId="kb-status">
      {t(`kb_version_status.${status}`)}
    </ToneTag>
  );
}

/** Expired, withdrawn and review-due flags: words, never colour alone. */
export function ArticleFlags({
  flags,
}: {
  flags: Pick<KbArticleRow, 'expired' | 'withdrawn' | 'review_due'>;
}) {
  const t = useLabel();
  return (
    <Space size={4} wrap>
      {flags.withdrawn && (
        <ToneTag tone="error" testId="kb-flag-withdrawn">
          {t('knowledge.flag.withdrawn')}
        </ToneTag>
      )}
      {flags.expired && (
        <ToneTag tone="warning" testId="kb-flag-expired">
          {t('knowledge.flag.expired')}
        </ToneTag>
      )}
      {flags.review_due && !flags.withdrawn && (
        <ToneTag tone="info" testId="kb-flag-review">
          {t('knowledge.flag.review_due')}
        </ToneTag>
      )}
    </Space>
  );
}
