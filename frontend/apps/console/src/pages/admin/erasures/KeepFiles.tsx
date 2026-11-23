import { Button, Checkbox, Flex, Input, List, Typography } from 'antd';
import { useMemo } from 'react';

import { usePersonUploads } from '@supportx/api-client';
import { EmptyText, lengthLimit, useDateTime, useLabel } from '@supportx/ui';

import { fileOwnerLabel } from './erasureText';

const KEEP_REASON_MAX = 500;

/**
 * The request's "Files to keep" (D-171 b): the person's uploads, by page, names and types only
 * (no download link: the request needs no content). A ticked file needs a reason, its field
 * labelled by the file's name; every file not ticked is deleted.
 */
export function KeepFiles({
  userId,
  kept,
  onChange,
  problems,
}: {
  userId: string;
  /** File ID → reason, for the ticked files. */
  kept: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
  /** Problems by file ID (the server's `keep_files.<id>` field errors). */
  problems: Record<string, string>;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const uploads = usePersonUploads(userId);
  const rows = useMemo(() => uploads.data?.pages.flatMap((p) => p.items) ?? [], [uploads.data]);
  return (
    <Flex vertical gap={8} data-testid="erasure-keep-files">
      <Typography.Text strong>{t('people_erasure.files.title')}</Typography.Text>
      <Typography.Text type="secondary">{t('people_erasure.files.explain')}</Typography.Text>
      <List
        loading={uploads.isPending}
        dataSource={rows}
        locale={{ emptyText: <EmptyText>{t('people_erasure.files.none')}</EmptyText> }}
        renderItem={(file) => {
          const ticked = file.id in kept;
          const reasonId = `erasure-keep-reason-${file.id}`;
          const problem = problems[file.id];
          return (
            <List.Item key={file.id}>
              <Flex vertical gap={4} style={{ width: '100%' }}>
                <Checkbox
                  checked={ticked}
                  onChange={(e) => {
                    onChange(
                      e.target.checked
                        ? { ...kept, [file.id]: '' }
                        : Object.fromEntries(Object.entries(kept).filter(([id]) => id !== file.id)),
                    );
                  }}
                  data-testid={`erasure-keep-${file.id}`}
                >
                  {t('people_erasure.files.keep', { name: file.name })}
                </Checkbox>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {file.attached_to == null
                    ? t('people_erasure.files.unattached')
                    : t('people_erasure.files.attached', {
                        what: fileOwnerLabel(t, file.attached_to),
                      })}
                  {' · '}
                  <span title={dates.format(file.created_at)}>
                    {dates.relative(file.created_at)}
                  </span>
                </Typography.Text>
                {ticked && (
                  <Flex vertical gap={2}>
                    <label htmlFor={reasonId}>
                      {t('people_erasure.files.keep_reason', { name: file.name })}
                    </label>
                    <Input
                      id={reasonId}
                      value={kept[file.id]}
                      count={lengthLimit(KEEP_REASON_MAX)}
                      status={problem === undefined ? undefined : 'error'}
                      aria-describedby={problem === undefined ? undefined : `${reasonId}-problem`}
                      onChange={(e) => {
                        onChange({ ...kept, [file.id]: e.target.value });
                      }}
                      data-testid={`erasure-keep-reason-${file.id}`}
                    />
                    {problem !== undefined && (
                      <Typography.Text type="danger" id={`${reasonId}-problem`}>
                        {problem}
                      </Typography.Text>
                    )}
                  </Flex>
                )}
              </Flex>
            </List.Item>
          );
        }}
      />
      {uploads.hasNextPage && (
        <Button
          onClick={() => void uploads.fetchNextPage()}
          loading={uploads.isFetchingNextPage}
          data-testid="erasure-keep-more"
        >
          {t('people_erasure.load_more')}
        </Button>
      )}
    </Flex>
  );
}
