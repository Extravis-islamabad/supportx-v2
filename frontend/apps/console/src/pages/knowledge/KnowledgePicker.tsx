import { BookOutlined } from '@ant-design/icons';
import { App, Button, Drawer, Empty, Flex, Input, List, Space, Typography } from 'antd';
import { useState } from 'react';

import {
  kbApplyCheck,
  useApplyKbArticle,
  useKbArticles,
  useKbTopics,
  type KbArticleRow,
  type KbAudience,
} from '@supportx/api-client';
import { reportError, useAppearance, useLabel } from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { articleLanguage, portalArticlePath, topicPath } from './model';

const escape = (text: string) =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/**
 * "Knowledge" in a reply, note or resolution editor (REQ-KB-063, D-121): find a published article
 * the technician may read, then insert its content (its images copied into their drafts) or its
 * link at the caret. Before a public insert the server says whether the people the record is for
 * may read the article; if not, the technician is warned first (D-108 (3)).
 */
export function KnowledgePicker({
  recordType,
  recordId,
  subject,
  audience,
  insert,
  onPick,
  buttonLabel,
}: {
  recordType: string;
  recordId: string;
  subject: string;
  audience: KbAudience;
  insert?: (html: string) => void;
  /** Instead of inserting: one "Link" button per article (the record's Knowledge card). */
  onPick?: (row: KbArticleRow) => Promise<void>;
  buttonLabel?: string;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const language = articleLanguage(locale);
  const { message, modal } = App.useApp();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState(subject);
  const query = useDebounced(search, 300);
  const list = useKbArticles({ view: 'published', language, search: query }, open);
  const topics = useKbTopics(open);
  const apply = useApplyKbArticle();
  const [busy, setBusy] = useState<string | null>(null);

  const run = (row: KbArticleRow, mode: 'content' | 'link') => {
    apply.mutate(
      { articleId: row.id, recordType, recordId, audience, mode, language },
      {
        onSuccess: (done) => {
          if (mode === 'content') {
            insert?.(done.html);
          } else {
            const href = portalArticlePath(done.article_id);
            insert?.(`<p><a href="${href}">${escape(`${done.display_id} ${done.title}`)}</a></p>`);
          }
          if (done.images_not_copied.length > 0) {
            void message.warning(
              t('knowledge.picker.images_left_out', { count: done.images_not_copied.length }),
            );
          }
          void message.success(t(`knowledge.picker.inserted_${mode}`));
          setOpen(false);
        },
        onError: reportError,
        onSettled: () => {
          setBusy(null);
        },
      },
    );
  };

  const choose = async (row: KbArticleRow, mode: 'content' | 'link') => {
    setBusy(`${row.id}:${mode}`);
    try {
      // The server's answer, never worked out here (coordinator, D-121 build rule 1).
      const check =
        audience === 'public'
          ? await kbApplyCheck(row.id, recordType, recordId, audience)
          : { visible_to_requester: null };
      if (check.visible_to_requester === false) {
        modal.confirm({
          title: t('knowledge.picker.warning_title'),
          content: (
            <span data-testid="kb-picker-warning">{t('knowledge.picker.warning_text')}</span>
          ),
          okText: t(`knowledge.picker.insert_${mode}`),
          cancelText: t('actions.cancel'),
          onOk: () => {
            run(row, mode);
          },
          onCancel: () => {
            setBusy(null);
          },
        });
        return;
      }
      run(row, mode);
    } catch (error) {
      setBusy(null);
      reportError(error);
    }
  };

  return (
    <>
      <Button
        size="small"
        type="text"
        icon={<BookOutlined />}
        onMouseDown={(event) => {
          event.preventDefault(); // keep the editor's caret
        }}
        onClick={() => {
          setSearch(subject);
          setOpen(true);
        }}
        data-testid="kb-picker-open"
      >
        {buttonLabel ?? t('knowledge.picker.button')}
      </Button>
      <Drawer
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        title={t('knowledge.picker.title')}
        width={480}
        destroyOnHidden
        data-testid="kb-picker"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input.Search
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
            }}
            placeholder={t('knowledge.picker.search')}
            aria-label={t('knowledge.picker.search')}
            allowClear
            data-testid="kb-picker-search"
          />
          <List<KbArticleRow>
            loading={list.isFetching && list.data === undefined}
            dataSource={list.data ?? []}
            locale={{ emptyText: <Empty description={t('knowledge.picker.none')} /> }}
            renderItem={(row) => (
              <List.Item key={row.id} data-testid={`kb-picker-item-${row.display_id}`}>
                <Flex vertical gap={4} style={{ width: '100%', minWidth: 0 }}>
                  <Typography.Text strong dir="auto" lang={row.language}>
                    {row.title}
                  </Typography.Text>
                  <Typography.Text type="secondary" ellipsis>
                    {[row.display_id, ...topicPath(topics.data ?? [], row.topic_id, language)].join(
                      ' · ',
                    )}
                  </Typography.Text>
                  {onPick !== undefined ? (
                    <Button
                      size="small"
                      type="primary"
                      style={{ alignSelf: 'flex-start' }}
                      loading={busy === `${row.id}:pick`}
                      onClick={() => {
                        setBusy(`${row.id}:pick`);
                        onPick(row)
                          .then(() => {
                            setOpen(false);
                          })
                          .catch(reportError)
                          .finally(() => {
                            setBusy(null);
                          });
                      }}
                      data-testid={`kb-picker-pick-${row.display_id}`}
                    >
                      {t('knowledge.picker.link_here')}
                    </Button>
                  ) : (
                    <Space wrap>
                      <Button
                        size="small"
                        type="primary"
                        loading={busy === `${row.id}:content`}
                        onClick={() => void choose(row, 'content')}
                        data-testid={`kb-picker-content-${row.display_id}`}
                      >
                        {t('knowledge.picker.insert_content')}
                      </Button>
                      <Button
                        size="small"
                        loading={busy === `${row.id}:link`}
                        onClick={() => void choose(row, 'link')}
                        data-testid={`kb-picker-link-${row.display_id}`}
                      >
                        {t('knowledge.picker.insert_link')}
                      </Button>
                    </Space>
                  )}
                </Flex>
              </List.Item>
            )}
          />
        </Space>
      </Drawer>
    </>
  );
}
