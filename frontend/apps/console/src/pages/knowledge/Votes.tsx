import { DislikeOutlined, LikeOutlined } from '@ant-design/icons';
import { Button, Card, Flex, Input, List, Radio, Space, Table, Typography } from 'antd';
import { useState } from 'react';

import {
  useKbScores,
  useKbVote,
  type KbArticle,
  type KbVersion,
  type KbVoteReason,
} from '@supportx/api-client';
import { useIsolate } from '@supportx/labels';
import {
  EmptyText,
  FormProblem,
  lengthLimit,
  useAppearance,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

// "Did this help?" (REQ-KB-069, D-125): one vote per reader and published version, changed in
// place; scores and feedback (never who) for those who edit or approve the article.

const REASONS: readonly KbVoteReason[] = [
  'steps_did_not_work',
  'out_of_date',
  'hard_to_follow',
  'not_what_i_needed',
  'other',
];
const COMMENT_MAX = 1000;

export function HelpfulPrompt({ article, version }: { article: KbArticle; version: KbVersion }) {
  const t = useLabel();
  const vote = useKbVote(article.id);
  const problem = useFormProblem();
  const mine = article.my_vote ?? null;
  const current = mine?.version_id === version.id ? mine : null;
  const [asking, setAsking] = useState(false);
  const [changing, setChanging] = useState(false);
  const [reason, setReason] = useState<KbVoteReason>();
  const [comment, setComment] = useState('');

  const send = (helpful: boolean) => {
    problem.clear();
    vote.mutate(
      {
        version_id: version.id,
        helpful,
        reason: helpful ? null : (reason ?? null),
        comment: helpful ? null : comment.trim() || null,
      },
      {
        onSuccess: () => {
          setAsking(false);
          setChanging(false);
        },
        onError: (error) => {
          problem.show(error);
        },
      },
    );
  };

  if (current !== null && !changing) {
    return (
      <Flex align="center" gap={8} wrap data-testid="kb-vote-done">
        <Typography.Text type="secondary">
          {t(current.helpful ? 'knowledge.vote.thanks_yes' : 'knowledge.vote.thanks_no')}
        </Typography.Text>
        <Button
          type="link"
          size="small"
          onClick={() => {
            setChanging(true);
          }}
          data-testid="kb-vote-change"
        >
          {t('knowledge.vote.change')}
        </Button>
      </Flex>
    );
  }
  return (
    <Card size="small" data-testid="kb-vote">
      <Space direction="vertical" style={{ width: '100%' }}>
        <Flex align="center" gap={8} wrap>
          <Typography.Text strong>{t('knowledge.vote.question')}</Typography.Text>
          <Button
            icon={<LikeOutlined />}
            loading={vote.isPending && !asking}
            onClick={() => {
              send(true);
            }}
            data-testid="kb-vote-yes"
          >
            {t('knowledge.vote.yes')}
          </Button>
          <Button
            icon={<DislikeOutlined />}
            aria-expanded={asking}
            onClick={() => {
              setAsking(true);
            }}
            data-testid="kb-vote-no"
          >
            {t('knowledge.vote.no')}
          </Button>
        </Flex>
        {asking && (
          <Space direction="vertical" style={{ width: '100%' }} data-testid="kb-vote-why">
            <Typography.Text>{t('knowledge.vote.reason')}</Typography.Text>
            <Radio.Group
              value={reason}
              onChange={(event) => {
                setReason(event.target.value as KbVoteReason);
              }}
            >
              <Space direction="vertical">
                {REASONS.map((code) => (
                  <Radio key={code} value={code} data-testid={`kb-vote-reason-${code}`}>
                    {t(`kb_vote_reason.${code}`)}
                  </Radio>
                ))}
              </Space>
            </Radio.Group>
            <Input.TextArea
              aria-label={t('knowledge.vote.comment')}
              placeholder={t('knowledge.vote.comment')}
              value={comment}
              count={lengthLimit(COMMENT_MAX)}
              autoSize={{ minRows: 2, maxRows: 6 }}
              onChange={(event) => {
                setComment(event.target.value);
              }}
              data-testid="kb-vote-comment"
            />
            <FormProblem problem={problem} />
            <Flex gap={8}>
              <Button
                type="primary"
                loading={vote.isPending}
                onClick={() => {
                  send(false);
                }}
                data-testid="kb-vote-send"
              >
                {t('knowledge.vote.send')}
              </Button>
              <Button
                onClick={() => {
                  setAsking(false);
                  setChanging(false);
                }}
              >
                {t('actions.cancel')}
              </Button>
            </Flex>
          </Space>
        )}
      </Space>
    </Card>
  );
}

/** The Feedback tab: the score now, every version's, and what readers said (never who). */
export function FeedbackPanel({ article }: { article: KbArticle }) {
  const t = useLabel();
  const isolate = useIsolate();
  const { intlLocale } = useAppearance();
  const allowed = article.can_edit || article.can_approve;
  const scores = useKbScores(article.id, allowed);
  if (!allowed) return <EmptyText>{t('knowledge.feedback.for_editors')}</EmptyText>;
  if (scores.data === undefined) return null;
  const { helpful, not_helpful: notHelpful, versions, feedback } = scores.data;
  const dateFormat = new Intl.DateTimeFormat(intlLocale, { dateStyle: 'medium' });
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }} data-testid="kb-feedback">
      <Typography.Text data-testid="kb-feedback-score">
        {helpful + notHelpful === 0
          ? t('knowledge.feedback.none')
          : t('knowledge.feedback.score', {
              helpful: isolate(String(helpful)),
              total: isolate(String(helpful + notHelpful)),
            })}
      </Typography.Text>
      {versions.length > 0 && (
        <Table
          size="small"
          rowKey="version_id"
          pagination={false}
          dataSource={versions}
          data-testid="kb-feedback-versions"
          columns={[
            {
              key: 'version',
              title: t('knowledge.feedback.version'),
              render: (_, row) =>
                t('knowledge.feedback.version_row', {
                  number: isolate(String(row.number)),
                  language: t(`locale.${row.language}`),
                }),
            },
            { key: 'helpful', dataIndex: 'helpful', title: t('knowledge.vote.yes'), align: 'end' },
            {
              key: 'not_helpful',
              dataIndex: 'not_helpful',
              title: t('knowledge.vote.no'),
              align: 'end',
            },
          ]}
        />
      )}
      <Typography.Text strong>{t('knowledge.feedback.said')}</Typography.Text>
      <List
        size="small"
        dataSource={feedback}
        locale={{ emptyText: <EmptyText>{t('knowledge.feedback.no_comments')}</EmptyText> }}
        renderItem={(item) => (
          <List.Item data-testid="kb-feedback-item">
            <Space direction="vertical" size={2}>
              <Typography.Text type="secondary">
                {[
                  item.reason === null ? null : t(`kb_vote_reason.${item.reason}`),
                  t('knowledge.feedback.version_row', {
                    number: isolate(String(item.version_number)),
                    language: t(`locale.${item.language}`),
                  }),
                  dateFormat.format(new Date(item.at)),
                ]
                  .filter((part) => part !== null)
                  .join(' · ')}
              </Typography.Text>
              {item.comment !== null && (
                <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                  <bdi>{item.comment}</bdi>
                </Typography.Paragraph>
              )}
            </Space>
          </List.Item>
        )}
      />
    </Space>
  );
}
