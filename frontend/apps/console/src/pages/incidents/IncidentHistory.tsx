import { Button, Empty, Flex, Segmented, Skeleton, Tag, Timeline, Typography } from 'antd';
import { SafetyCertificateOutlined } from '@ant-design/icons';
import { useMemo, useState } from 'react';
import { Link } from 'react-router';

import {
  useIncidentCatalogue,
  useIncidentCategories,
  useIncidentHistory,
  useUnits,
  type IncidentHistoryEntry,
} from '@supportx/api-client';
import { useAccess, useAppearance, useDateTime, useLabel } from '@supportx/ui';

import { categoryPath, statusLabel } from './labels';

type Change = IncidentHistoryEntry['changes'][number];

const CODED: Record<string, string> = {
  priority: 'priority',
  priority_source: 'priority_source',
  impact: 'impact',
  urgency: 'urgency',
  channel: 'work_item_channel',
  follow_reason: 'follow_reason',
  conversation_entry: 'conversation_entry',
  note_visibility: 'visibility',
};
const TIMES = new Set(['resolved_at', 'closed_at', 'last_reopened_at', 'first_responded_at']);
const PEOPLE = new Set([
  'requester_id',
  'on_behalf_of_id',
  'technician_id',
  'follower',
  'follower_access',
]);
// Flags: "not set" reads "No", not "(empty)".
const FLAGS = new Set(['handed_over_out_of_reach']);

/**
 * The History tab (REQ-WI-003/004): every save, newest first, in true order, with who, when, from
 * where, what changed from what to what, why, and which automation did it. Values are labels,
 * names and local times, never raw codes or IDs (rule d).
 */
export function IncidentHistory({ id }: { id: string }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const dates = useDateTime();
  const { can } = useAccess();
  const [actors, setActors] = useState<'all' | 'people' | 'automation'>('all');
  const history = useIncidentHistory(id, actors);
  const catalogue = useIncidentCatalogue();
  const categories = useIncidentCategories();
  const sites = useUnits('sites', can('sites.view'));
  const groups = useUnits('groups', can('groups.view'));
  const units = useMemo(
    () => new Map([...(sites.data ?? []), ...(groups.data ?? [])].map((u) => [u.id, u.name])),
    [sites.data, groups.data],
  );
  const entries = history.data?.pages.flatMap((page) => page.items) ?? [];
  // People named in changed values, from every page (QA BUG-03).
  const people = useMemo(
    () =>
      Object.assign({}, ...(history.data?.pages.map((page) => page.people) ?? [])) as Record<
        string,
        { display_name: string; email: string } | undefined
      >,
    [history.data],
  );

  const valueText = (change: Change, value: unknown): string => {
    if (FLAGS.has(change.field) && (value === null || value === undefined)) return t('history.no');
    if (value === null || value === undefined || value === '') return t('history.empty');
    if (change.field === 'status' && typeof value === 'string') {
      return statusLabel(t, catalogue.data, value, locale);
    }
    const prefix = CODED[change.field];
    if (prefix !== undefined && typeof value === 'string') return t(`${prefix}.${value}`);
    if (
      (change.field === 'status_reason_code' || change.field === 'assignment_reason') &&
      typeof value === 'string'
    ) {
      const reason = catalogue.data?.reasons.find((r) => r.code === value);
      return reason === undefined ? t('history.changed') : t(`reason.${reason.list}.${value}`);
    }
    if (TIMES.has(change.field) && typeof value === 'string') return dates.format(value);
    if (change.field === 'category_id' && typeof value === 'string') {
      return categoryPath(t, categories.data ?? [], value, locale) || t('history.changed');
    }
    if ((change.field === 'site_id' || change.field === 'group_id') && typeof value === 'string') {
      return units.get(value) ?? t('history.changed');
    }
    if (PEOPLE.has(change.field) && typeof value === 'string') {
      return people[value]?.display_name ?? t('history.changed');
    }
    if (change.field === 'description') return t('history.changed');
    if (typeof value === 'boolean') return t(value ? 'history.yes' : 'history.no');
    if (Array.isArray(value))
      return value.length === 0 ? t('history.empty') : value.join(t('list.separator'));
    if (typeof value === 'string' || typeof value === 'number') return String(value);
    return t('history.changed');
  };

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
        <Empty description={t('history.none')} />
      ) : (
        <Timeline
          items={entries.map((entry) => ({
            key: entry.change_id,
            children: (
              <div data-testid="inc-history-entry" data-kind={entry.kind}>
                <Typography.Text strong>{t(`change_kind.${entry.kind}`)}</Typography.Text>{' '}
                {entry.automation !== null && (
                  <Tag data-testid="inc-history-automatic">{t('incidents.history.automatic')}</Tag>
                )}
                {entry.audit_entry_id != null && (
                  <Link
                    to={`/admin/audit?entry=${entry.audit_entry_id}`}
                    data-testid="inc-history-audited"
                  >
                    <Tag icon={<SafetyCertificateOutlined />}>{t('incidents.history.audited')}</Tag>
                  </Link>
                )}
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
                  <ul style={{ margin: 0, paddingInlineStart: 20 }}>
                    {entry.changes.map((change) => (
                      <li key={change.field}>
                        {t('history.change', {
                          field: t(`work_item.field.${change.field}`),
                          old: valueText(change, change.old),
                          new: valueText(change, change.new),
                        })}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ),
          }))}
        />
      )}
      {history.hasNextPage && (
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
