import { BulbOutlined } from '@ant-design/icons';
import { Flex, Input, Switch, Table } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router';

import {
  knownErrorKeys,
  useKnownErrors,
  type KnownError,
  type Problem,
} from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import { EmptyText, PageHeader, ToneTag, useDateTime, useLabel } from '@supportx/ui';

import { useDebounced } from '../../useDebounced';

/** Plain text of a rich text value, for one-line excerpts. */
function excerpt(html: string | null | undefined): string {
  if (!html) return '';
  const text = new DOMParser().parseFromString(html, 'text/html').body.textContent;
  return text.length > 140 ? `${text.slice(0, 139)}…` : text;
}

/** The record header's marker (REQ-PRB-036): a known error, or a retired one. */
export function KnownErrorTag({ item }: { item: Problem }) {
  const t = useLabel();
  if (item.known_error_at == null) return null;
  const retired = item.known_error_retired_at != null;
  return (
    <ToneTag
      tone={retired ? 'default' : 'warning'}
      icon={<BulbOutlined />}
      testId="prb-known-error"
    >
      {t(retired ? 'problems.known_error.retired' : 'problems.known_error.tag')}
    </ToneTag>
  );
}

/**
 * The known error database (REQ-PRB-037): the known errors you may see, searched in title,
 * symptoms and workaround (never the root cause, D-140 Q7), retired ones kept and marked.
 */
export function KnownErrorsPage() {
  const t = useLabel();
  const { format } = useDateTime();
  const [search, setSearch] = useState('');
  const [retired, setRetired] = useState(true);
  const found = useKnownErrors(useDebounced(search.trim(), 300), retired);
  // Counts and flags follow at once (REQ-PRB-037 AC2): a problem changed, or an incident linked.
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: knownErrorKeys.all });
  useListChannel('problems', refresh);
  useListChannel('incidents', refresh);
  return (
    <Flex vertical gap={16} style={{ width: '100%' }} data-testid="known-errors">
      <PageHeader title={t('problems.known_error.database')} />
      <Flex gap={16} align="center" wrap>
        <Input.Search
          allowClear
          value={search}
          placeholder={t('problems.known_error.search')}
          aria-label={t('problems.known_error.search')}
          onChange={(e) => {
            setSearch(e.target.value);
          }}
          style={{ maxWidth: 420 }}
          data-testid="known-errors-search"
        />
        <label>
          <Flex gap={8} align="center">
            <Switch checked={retired} onChange={setRetired} data-testid="known-errors-retired" />
            {t('problems.known_error.include_retired')}
          </Flex>
        </label>
      </Flex>
      <div
        role="region"
        aria-label={t('problems.known_error.database')}
        tabIndex={0}
        style={{ overflowX: 'auto' }}
      >
        <Table<KnownError>
          rowKey="id"
          loading={found.isPending}
          dataSource={found.data ?? []}
          pagination={false}
          locale={{ emptyText: <EmptyText>{t('problems.known_error.none')}</EmptyText> }}
          columns={[
            {
              key: 'problem',
              title: t('nav.problems'),
              render: (_, row) => (
                <Flex vertical gap={2}>
                  <Link to={`/problems/${row.id}`} data-testid={`known-error-${row.display_id}`}>
                    <strong dir="ltr">{row.display_id}</strong> <bdi dir="auto">{row.subject}</bdi>
                  </Link>
                  {row.retired_at != null && (
                    <ToneTag tone="default">{t('problems.known_error.retired')}</ToneTag>
                  )}
                </Flex>
              ),
            },
            {
              key: 'symptoms',
              title: t('work_item.field.symptoms'),
              render: (_, row) => <bdi dir="auto">{excerpt(row.symptoms)}</bdi>,
            },
            {
              key: 'workaround',
              title: t('work_item.field.workaround'),
              render: (_, row) => <bdi dir="auto">{excerpt(row.workaround)}</bdi>,
            },
            {
              key: 'incidents',
              title: t('problems.known_error.incidents'),
              render: (_, row) => row.incidents,
            },
            {
              key: 'since',
              title: t('work_item.field.known_error_at'),
              render: (_, row) => format(row.known_error_at),
            },
          ]}
        />
      </div>
    </Flex>
  );
}
