import { Button, Flex, Input, List, Space, Typography } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import {
  useAddChangeChild,
  useChangeChildren,
  useRemoveChangeChild,
  type ChangeChild,
} from '@supportx/api-client';
import { EmptyText, FormProblem, WriteButton, useFormProblem, useLabel } from '@supportx/ui';

import { stageName, statusName } from '../staged/labels';

const PATHS: Record<string, string> = { change: '/changes/', release: '/releases/' };

/**
 * The change's child changes and releases (WP-045d S1; REQ-CHG-096): those you may see, with
 * their stage and status; a child is added by its number (CHG-… or REL-…) and taken off again.
 * Closing the change waits for every child, and says so.
 */
export function ChildrenPart({ id, canEdit }: { id: string; canEdit: boolean }) {
  const t = useLabel();
  const children = useChangeChildren(id);
  const add = useAddChangeChild();
  const remove = useRemoveChangeChild();
  const problem = useFormProblem();
  const [number, setNumber] = useState('');
  const rows = children.data ?? [];
  const open = rows.filter(
    (c) => c.status_category !== 'closed' && c.status_category !== 'canceled',
  );
  return (
    <Flex vertical gap={12} data-testid="change-children">
      <Typography.Paragraph type="secondary">{t('changes.children.help')}</Typography.Paragraph>
      {open.length > 0 && (
        <Typography.Text type="warning" data-testid="change-children-open">
          {t('changes.children.open', { count: open.length })}
        </Typography.Text>
      )}
      <List<ChangeChild>
        dataSource={rows}
        locale={{ emptyText: <EmptyText>{t('changes.children.none')}</EmptyText> }}
        renderItem={(c) => (
          <List.Item
            key={c.link_id}
            data-testid={`change-child-${c.display_id}`}
            actions={
              canEdit
                ? [
                    <Button
                      key="remove"
                      size="small"
                      danger
                      type="text"
                      onClick={() => {
                        remove.mutate(
                          { id, linkId: c.link_id },
                          {
                            onError: (error) => {
                              problem.show(error);
                            },
                          },
                        );
                      }}
                      data-testid={`change-child-${c.display_id}-remove`}
                    >
                      {t('changes.children.remove')}
                    </Button>,
                  ]
                : []
            }
          >
            <Space wrap>
              <Link to={`${PATHS[c.type] ?? '/changes/'}${c.record_id}`}>
                <bdi dir="ltr" style={{ fontWeight: 600 }}>
                  {c.display_id}
                </bdi>
              </Link>
              <span>{c.subject}</span>
              {c.stage && (
                <Typography.Text type="secondary">{stageName(t, c.stage)}</Typography.Text>
              )}
              <Typography.Text>{statusName(t, c.status)}</Typography.Text>
            </Space>
          </List.Item>
        )}
      />
      {canEdit && (
        <Space.Compact style={{ maxWidth: 420 }}>
          <Input
            value={number}
            onChange={(e) => {
              setNumber(e.target.value);
            }}
            placeholder={t('changes.children.number')}
            aria-label={t('changes.children.number')}
            data-testid="change-child-number"
          />
          <WriteButton
            disabled={number.trim() === ''}
            whyDisabled={t('changes.children.why_number')}
            loading={add.isPending}
            onClick={() => {
              add.mutate(
                { id, number },
                {
                  onSuccess: () => {
                    setNumber('');
                    problem.clear();
                  },
                  onError: (error) => {
                    problem.show(error);
                  },
                },
              );
            }}
            data-testid="change-child-add"
          >
            {t('changes.children.add')}
          </WriteButton>
        </Space.Compact>
      )}
      <FormProblem problem={problem} />
    </Flex>
  );
}
