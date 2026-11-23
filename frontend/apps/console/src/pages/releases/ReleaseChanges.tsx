import { Alert, Flex, List, Select, Space, Typography } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import {
  ApiError,
  useAddReleaseChange,
  useChanges,
  useReleaseChanges,
  useRemoveReleaseChange,
} from '@supportx/api-client';
import { EmptyText, WriteButton, reportError, useAccess, useLabel } from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { stageName, statusName } from './labels';

/** Number or title, as the changes list searches (the API applies what you may see). */
function searchFilter(text: string): string | undefined {
  const needle = text.trim();
  if (needle === '') return undefined;
  return JSON.stringify({
    or: [
      { field: 'subject', op: 'contains', value: needle },
      { field: 'display_id', op: 'eq', value: needle.toUpperCase() },
    ],
  });
}

/**
 * The changes in a release (WP-058b S1; REQ-REL-033): each one's number, title, stage and
 * status, linked; one you may not see shows only that it is there. A change is in one open
 * release at a time: adding one already in another is refused with that release's number.
 * Live through the record channel (the history the link writes on both records).
 */
export function ReleaseChangesPart({ id }: { id: string }) {
  const t = useLabel();
  const { can } = useAccess();
  const changes = useReleaseChanges(id);
  const add = useAddReleaseChange();
  const remove = useRemoveReleaseChange();
  // Why the change was not added, by its field code (the release it is already in).
  const [refused, setRefused] = useState<string>();
  const [text, setText] = useState('');
  const search = useDebounced(text, 300);
  const found = useChanges({ filter: searchFilter(search) });
  const may = can('releases.edit');
  const inIt = new Set((changes.data ?? []).map((c) => c.id));
  const options = (found.data?.items ?? [])
    .filter((c) => !inIt.has(c.id))
    .map((c) => ({ value: c.id, label: `${c.display_id} ${c.subject}` }));
  return (
    <Flex vertical gap={12} data-testid="release-changes">
      {may && (
        <Flex vertical gap={4}>
          <Typography.Text strong id="release-change-add-label">
            {t('releases.changes.add')}
          </Typography.Text>
          <Select<string>
            showSearch
            filterOption={false}
            value={null}
            placeholder={t('releases.changes.search')}
            onSearch={setText}
            options={options}
            notFoundContent={<EmptyText>{t('releases.changes.no_match')}</EmptyText>}
            onChange={(changeId) => {
              setRefused(undefined);
              add.mutate(
                { id, changeId },
                {
                  onError: (error) => {
                    const why =
                      error instanceof ApiError
                        ? error.fieldErrors.find((f) => f.field.endsWith('change_id'))
                        : undefined;
                    if (why === undefined) {
                      reportError(error);
                      return;
                    }
                    setRefused(t(why.message_key, why.params ?? {}));
                  },
                },
              );
            }}
            loading={add.isPending}
            style={{ maxWidth: 480, width: '100%' }}
            aria-labelledby="release-change-add-label"
            data-testid="release-change-add"
          />
          {refused !== undefined && (
            <Alert
              type="warning"
              showIcon
              role="alert"
              message={refused}
              closable
              onClose={() => {
                setRefused(undefined);
              }}
              data-testid="release-change-refused"
            />
          )}
        </Flex>
      )}
      <List
        dataSource={changes.data ?? []}
        locale={{ emptyText: <EmptyText>{t('releases.changes.none')}</EmptyText> }}
        renderItem={(c) => (
          <List.Item
            key={c.id}
            data-testid={`release-change-${c.id}`}
            actions={
              may
                ? [
                    <WriteButton
                      key="remove"
                      size="small"
                      onClick={() => {
                        remove.mutate({ id, changeId: c.id });
                      }}
                      aria-label={t('releases.changes.remove_of', {
                        id: c.display_id ?? t('releases.changes.hidden'),
                      })}
                      data-testid={`release-change-remove-${c.id}`}
                    >
                      {t('releases.changes.remove')}
                    </WriteButton>,
                  ]
                : []
            }
          >
            {c.visible ? (
              <Space wrap>
                <Link to={`/changes/${c.id}`}>
                  <bdi dir="ltr">{c.display_id}</bdi>
                </Link>
                <bdi>{c.subject}</bdi>
                <span>{stageName(t, c.stage)}</span>
                <span>{statusName(t, c.status)}</span>
              </Space>
            ) : (
              <Typography.Text type="secondary">{t('releases.changes.hidden')}</Typography.Text>
            )}
          </List.Item>
        )}
      />
    </Flex>
  );
}
