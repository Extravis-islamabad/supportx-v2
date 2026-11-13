import { Alert, Flex, Form, Input, List, Typography } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import {
  useCreateReleaseFollowUp,
  usePlanSections,
  useReleaseFollowUps,
  type StageMove,
} from '@supportx/api-client';
import {
  EditDialog,
  EmptyText,
  RichTextView,
  WriteButton,
  lengthLimit,
  reportError,
  useAccess,
  useLabel,
} from '@supportx/ui';

const FAILED = 'deployment_failed';
const ROLLED_BACK = 'deployment_rolled_back';
const TITLE_MAX = 200;

type Kind = 'problem' | 'release';

/**
 * A failed deployment's guided path (REQ-REL-053): the failure is named on the release with its
 * backout plan right there, the release manager marks it rolled back through the life cycle's
 * own move (reason and all), and from a failed or rolled-back release one makes the problem it
 * caused and a follow-up release, each linked at once and listed here.
 */
export function ReleaseFailed({
  id,
  displayId,
  subject,
  status,
  moves,
  onMove,
}: {
  id: string;
  displayId: string;
  subject: string;
  status: string;
  moves: readonly StageMove[];
  onMove: (move: StageMove) => void;
}) {
  const t = useLabel();
  const { can } = useAccess();
  const after = status === FAILED || status === ROLLED_BACK;
  const sections = usePlanSections(status === FAILED ? id : '');
  const followUps = useReleaseFollowUps(id, after);
  const create = useCreateReleaseFollowUp();
  const [making, setMaking] = useState<{ kind: Kind; title: string; key: string }>();
  if (!after) return null;
  const backout = (sections.data ?? []).find((s) => s.section === 'backout');
  const rollBack = moves.find((m) => m.to_status === ROLLED_BACK);
  const start = (kind: Kind) => {
    setMaking({
      kind,
      key: crypto.randomUUID(),
      title:
        kind === 'problem'
          ? t('releases.failed.problem_title', { id: displayId, subject })
          : t('releases.failed.follow_up_title', { subject }),
    });
  };
  const found = followUps.data ?? [];
  return (
    <>
      <Alert
        type={status === FAILED ? 'error' : 'warning'}
        showIcon
        style={{ marginBottom: 16 }}
        data-testid="release-failed"
        message={
          status === FAILED ? t('releases.failed.title') : t('releases.failed.rolled_back_title')
        }
        description={
          <Flex vertical gap={8}>
            {status === FAILED && (
              <>
                <Typography.Text strong>{t('releases.failed.backout')}</Typography.Text>
                {backout?.content ? (
                  <RichTextView html={backout.content} testId="release-failed-backout" />
                ) : (
                  <EmptyText>{t('releases.failed.no_backout')}</EmptyText>
                )}
              </>
            )}
            <Flex gap={8} wrap>
              {status === FAILED && rollBack !== undefined && (
                <WriteButton
                  danger
                  disabled={!rollBack.allowed}
                  whyDisabled={t('releases.failed.why_not')}
                  onClick={() => {
                    onMove(rollBack);
                  }}
                  data-testid="release-mark-rolled-back"
                >
                  {t('releases.failed.mark_rolled_back')}
                </WriteButton>
              )}
              {can('problems.create') && (
                <WriteButton
                  onClick={() => {
                    start('problem');
                  }}
                  data-testid="release-create-problem"
                >
                  {t('releases.failed.create_problem')}
                </WriteButton>
              )}
              {can('releases.create') && (
                <WriteButton
                  onClick={() => {
                    start('release');
                  }}
                  data-testid="release-create-follow-up"
                >
                  {t('releases.failed.create_follow_up')}
                </WriteButton>
              )}
            </Flex>
            {found.length > 0 && (
              <List
                size="small"
                data-testid="release-follow-ups"
                dataSource={found}
                renderItem={(f) => (
                  <List.Item key={f.id}>
                    <Link to={`/${f.type === 'problem' ? 'problems' : 'releases'}/${f.id}`}>
                      <bdi dir="auto">{`${f.display_id} ${f.subject}`}</bdi>
                    </Link>
                    <Typography.Text type="secondary">
                      {t(`releases.failed.relation.${f.relation}`)}
                    </Typography.Text>
                  </List.Item>
                )}
              />
            )}
          </Flex>
        }
      />
      {making !== undefined && (
        <EditDialog
          open
          title={
            making.kind === 'problem'
              ? t('releases.failed.create_problem')
              : t('releases.failed.create_follow_up')
          }
          okText={
            making.kind === 'problem'
              ? t('releases.failed.create_problem')
              : t('releases.failed.create_follow_up')
          }
          saving={create.isPending}
          okDisabled={making.title.trim() === ''}
          dirty={false}
          onCancel={() => {
            setMaking(undefined);
          }}
          onOk={() => {
            create.mutate(
              { id, kind: making.kind, subject: making.title.trim(), key: making.key },
              {
                onSuccess: () => {
                  setMaking(undefined);
                },
                onError: reportError,
              },
            );
          }}
          testId="release-follow-up-dialog"
        >
          <Form layout="vertical">
            <Form.Item label={t('work_item.field.subject')} htmlFor="follow-up-title">
              <Input
                id="follow-up-title"
                value={making.title}
                count={lengthLimit(TITLE_MAX)}
                onChange={(e) => {
                  setMaking({ ...making, title: e.target.value });
                }}
                data-testid="release-follow-up-title"
              />
            </Form.Item>
          </Form>
        </EditDialog>
      )}
    </>
  );
}
