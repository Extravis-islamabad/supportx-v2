import { Button, Empty, Flex, Skeleton, Timeline, Typography } from 'antd';
import { useMemo } from 'react';

import {
  useAnnouncementHistory,
  useUnits,
  type AnnouncementHistoryEntry,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { useAccess, useAppearance, useLabel } from '@supportx/ui';

type Change = AnnouncementHistoryEntry['changes'][number];
type Translate = ReturnType<typeof useLabel>;

const LABELLED: Record<string, string> = {
  status: 'announcement_status',
  severity: 'announcement_severity',
  audience: 'announcement_audience',
};

/**
 * A changed value as people read it: labels for codes, local date-times, unit names for site
 * and group IDs. Never a raw code or ID (rule d): an unknown unit is counted, not shown.
 */
function valueText(
  change: Change,
  value: unknown,
  t: Translate,
  format: Intl.DateTimeFormat,
  units: Map<string, string>,
  listFormat: (items: readonly string[]) => string,
): string {
  if (value === null || value === undefined || value === '') return t('history.empty');
  const prefix = LABELLED[change.field];
  if (prefix !== undefined && typeof value === 'string') return t(`${prefix}.${value}`);
  if (typeof value === 'boolean') return t(value ? 'history.yes' : 'history.no');
  if (change.field === 'publish_from' || change.field === 'publish_until') {
    return typeof value === 'string' ? format.format(new Date(value)) : t('history.changed');
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return t('history.empty');
    const names = value.flatMap((id) => units.get(String(id)) ?? []);
    return names.length === value.length
      ? listFormat(names)
      : t('history.units', { count: value.length });
  }
  if (change.field === 'owner_id') return t('history.changed');
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  return t('history.changed');
}

/** The History tab: every save, newest first, with who, when, from where, what, and why. */
export function AnnouncementHistory({ id }: { id: string }) {
  const t = useLabel();
  const listFormat = useListFormat();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const history = useAnnouncementHistory(id);
  const sites = useUnits('sites', can('sites.view'));
  const groups = useUnits('groups', can('groups.view'));
  const units = useMemo(
    () => new Map([...(sites.data ?? []), ...(groups.data ?? [])].map((u) => [u.id, u.name])),
    [sites.data, groups.data],
  );
  const format = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });
  const entries = history.data?.pages.flatMap((page) => page.items) ?? [];
  if (history.isPending) return <Skeleton active />;
  if (entries.length === 0) return <Empty description={t('history.none')} />;
  return (
    <Flex vertical gap={8} data-testid="ann-history">
      <Timeline
        items={entries.map((entry) => ({
          key: entry.version,
          children: (
            <div data-testid={`history-${String(entry.version)}`}>
              <Typography.Text strong>{t(`change_kind.${entry.kind}`)}</Typography.Text>{' '}
              <Typography.Text type="secondary">
                {t('history.by', {
                  name: entry.actor_name ?? t(`actor_type.${entry.actor_type}`),
                  time: format.format(new Date(entry.occurred_at)),
                  source: t(`change_source.${entry.source}`),
                })}
              </Typography.Text>
              {entry.reason !== null && (
                <Typography.Paragraph
                  italic
                  style={{ marginBottom: 4 }}
                  data-testid={`history-reason-${String(entry.version)}`}
                >
                  {t('history.reason', { reason: entry.reason })}
                </Typography.Paragraph>
              )}
              {entry.kind !== 'created' && entry.changes.length > 0 && (
                <ul style={{ margin: 0, paddingInlineStart: 20 }}>
                  {entry.changes.map((change) => (
                    <li key={change.field}>
                      {t('history.change', {
                        field: t(`announcement.field.${change.field}`),
                        old: valueText(change, change.old, t, format, units, listFormat),
                        new: valueText(change, change.new, t, format, units, listFormat),
                      })}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ),
        }))}
      />
      {history.hasNextPage && (
        <Button
          onClick={() => void history.fetchNextPage()}
          loading={history.isFetchingNextPage}
          style={{ alignSelf: 'center' }}
        >
          {t('announcements.more')}
        </Button>
      )}
    </Flex>
  );
}
