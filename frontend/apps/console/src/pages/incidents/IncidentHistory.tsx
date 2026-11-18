import { Button, Flex, Segmented, Skeleton, Tag, Timeline, Typography } from 'antd';
import { SafetyCertificateOutlined } from '@ant-design/icons';
import { useEffect, useState } from 'react';
import { Link } from 'react-router';

import { EmptyText, useAppearance, useDateTime, useLabel } from '@supportx/ui';

import { useHistoryWords, type HistoryActors } from './historyWords';

/**
 * The History tab (REQ-WI-003/004): every save, newest first, in true order, with who, when, from
 * where, what changed from what to what, why, and which automation did it. Values are labels,
 * names and local times, never raw codes or IDs (rule d).
 */
// Pages of history a printout loads by itself before saying the rest are left out.
const PRINT_PAGES = 20;

export function IncidentHistory({
  id,
  base = 'incidents',
  printing = false,
  onLoadingChange,
}: {
  id: string;
  /** The record's type prefix: a problem's history uses the same view (WP-044c). */
  base?: 'incidents' | 'problems' | 'changes';
  /**
   * The printable page (WP-046b S4; lane C): every page loaded by itself, up to PRINT_PAGES,
   * no buttons; when more remain the page says so instead of silently leaving them out.
   */
  printing?: boolean;
  /** The printable page hears whether pages are still loading, so Print waits (lane C). */
  onLoadingChange?: (loading: boolean) => void;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const [actors, setActors] = useState<HistoryActors>('all');
  const { history, entries, sentences, whyText } = useHistoryWords(id, actors, base);
  const pages = history.data?.pages.length ?? 0;
  useEffect(() => {
    if (printing && history.hasNextPage && !history.isFetchingNextPage && pages < PRINT_PAGES) {
      void history.fetchNextPage();
    }
  }, [printing, history, pages]);
  const stillLoading =
    history.isPending || history.isFetchingNextPage || (history.hasNextPage && pages < PRINT_PAGES);
  useEffect(() => {
    if (printing) onLoadingChange?.(stillLoading);
  }, [printing, stillLoading, onLoadingChange]);
  const { intlLocale } = useAppearance();
  return (
    <Flex vertical gap={8} data-testid="inc-history">
      <Segmented<'all' | 'people' | 'automation'>
        value={actors}
        onChange={setActors}
        options={[
          { value: 'all', label: t('incidents.history.all') },
          { value: 'people', label: t('incidents.history.people') },
          { value: 'automation', label: t('incidents.history.automation') },
        ]}
        style={{ alignSelf: 'flex-start' }}
        data-testid="inc-history-filter"
      />
      {history.isPending ? (
        <Skeleton active />
      ) : entries.length === 0 ? (
        <EmptyText>{t('history.none')}</EmptyText>
      ) : (
        <Timeline
          items={entries.map((entry) => ({
            key: entry.change_id,
            children: (
              <div data-testid="inc-history-entry" data-kind={entry.kind}>
                <Typography.Text strong>{t(`change_kind.${entry.kind}`)}</Typography.Text>{' '}
                {entry.automation !== null && (
                  <>
                    <Tag data-testid="inc-history-automatic">
                      {t('incidents.history.automatic')}
                    </Tag>
                    {/* A real space after each tag: the tag's margin is not a word gap (QA C5). */}{' '}
                  </>
                )}
                {entry.bulk_job_id != null && (
                  <>
                    {/* REQ-INC-120 AC4: a bulk change names its job. */}
                    <Tag data-testid="inc-history-bulk">{t('incidents.history.bulk')}</Tag>{' '}
                  </>
                )}
                {whyText(entry) !== '' && (
                  <Typography.Paragraph
                    type="secondary"
                    style={{ marginBottom: 4 }}
                    data-testid="inc-history-why"
                  >
                    {whyText(entry)}
                  </Typography.Paragraph>
                )}
                {entry.audit_entry_id != null && (
                  <Link
                    to={`/admin/audit?entry=${entry.audit_entry_id}`}
                    data-testid="inc-history-audited"
                  >
                    <Tag icon={<SafetyCertificateOutlined />}>{t('incidents.history.audited')}</Tag>
                  </Link>
                )}
                {entry.audit_entry_id != null && ' '}
                <Typography.Text type="secondary">
                  {t('history.by', {
                    name: entry.actor_name ?? t(`actor_type.${entry.actor_type}`),
                    time: dates.format(entry.occurred_at),
                    source: t(`change_source.${entry.source}`),
                  })}
                </Typography.Text>
                {entry.reason !== null && (
                  <Typography.Paragraph italic style={{ marginBottom: 4 }}>
                    {t('history.reason', { reason: entry.reason })}
                  </Typography.Paragraph>
                )}
                {entry.kind !== 'created' && entry.changes.length > 0 && (
                  // Sentences with who did it (Haider, 2026-11-10), never "field: old → new".
                  <ul style={{ margin: 0, paddingInlineStart: 20 }}>
                    {sentences(entry).map((line, index) => (
                      <li key={index}>{line}</li>
                    ))}
                  </ul>
                )}
              </div>
            ),
          }))}
        />
      )}
      {printing && history.hasNextPage && pages >= PRINT_PAGES && (
        <Typography.Text type="secondary" data-testid="inc-history-cut">
          {t('incidents.print.history_cut', {
            n: new Intl.NumberFormat(intlLocale).format(entries.length),
          })}
        </Typography.Text>
      )}
      {!printing && history.hasNextPage && (
        <Button
          onClick={() => void history.fetchNextPage()}
          loading={history.isFetchingNextPage}
          style={{ alignSelf: 'center' }}
        >
          {t('incidents.more')}
        </Button>
      )}
    </Flex>
  );
}
