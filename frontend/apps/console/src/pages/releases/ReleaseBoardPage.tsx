import { ThunderboltOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Flex, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  releaseKeys,
  stagedPanelQuery,
  useReleaseSettings,
  useReleases,
  type ReleaseListItem,
  type StageMove,
} from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import {
  ListPage,
  PageHeader,
  StageBoard,
  ToneTag,
  reportError,
  usePageCrumbs,
  useLabel,
  type BoardCard,
} from '@supportx/ui';

import { StatusTag } from '../incidents/tags';
import { EMERGENCY_PATH, RELEASE_STAGES, stageName } from './labels';
import { MoveDialog } from './MoveDialog';

interface ReleaseCard extends BoardCard {
  release: ReleaseListItem;
}

/**
 * Releases by stage (REQ-REL-056): the open releases in their stage's column, live. Dropping a
 * card on a stage runs the move the release offers into that stage, through its own move dialog
 * (with what the move asks for); a stage it may not reach from where it is, or not by you, is
 * refused in words and the card stays (AC1). Other viewers see a card move when the move is made
 * (the type's list channel, AC2).
 */
export function ReleaseBoardPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const settings = useReleaseSettings();
  const list = useReleases({ view: 'open' });
  const [moving, setMoving] = useState<{ id: string; version: number; move: StageMove }>();
  usePageCrumbs([
    { label: t('nav.releases'), path: '/releases' },
    { label: t('releases.board.title') },
  ]);
  useListChannel('releases', () => {
    void queryClient.invalidateQueries({ queryKey: [...releaseKeys.all, 'list'] });
  });
  useEffect(() => {
    if (list.error) reportError(list.error);
  }, [list.error]);
  const cards: ReleaseCard[] = (list.data?.items ?? []).map((release) => ({
    id: release.id,
    column: release.stage ?? RELEASE_STAGES[0] ?? 'submission',
    name: release.display_id,
    release,
  }));
  const onMove = async (card: ReleaseCard, stage: string): Promise<string | null> => {
    // The moves this release offers now, fetched fresh: never a stale button.
    const panel = await queryClient.query({
      ...stagedPanelQuery('releases', card.id),
      staleTime: 0,
    });
    const into = panel.moves.filter((m) => m.to_stage === stage);
    const allowed = into.find((m) => m.allowed);
    if (allowed === undefined) {
      const reason = into[0]?.reason;
      return reason
        ? t(`action_reason.${reason}`)
        : t('releases.board.no_move', { stage: stageName(t, stage) });
    }
    setMoving({ id: card.id, version: panel.version, move: allowed });
    return null;
  };
  return (
    <ListPage
      testId="releases-board"
      header={
        <PageHeader
          title={t('releases.board.title')}
          testId="releases-board-header"
          extra={
            <Button
              icon={<UnorderedListOutlined />}
              onClick={() => void navigate('/releases')}
              data-testid="releases-board-list"
            >
              {t('releases.board.list')}
            </Button>
          }
        />
      }
    >
      <StageBoard<ReleaseCard>
        label={t('releases.board.title')}
        testId="release-board"
        columns={RELEASE_STAGES.map((stage) => ({ key: stage, title: stageName(t, stage) }))}
        cards={cards}
        onMove={onMove}
        renderCard={(card) => (
          <Flex vertical gap={4}>
            <Flex gap={6} align="center" wrap>
              <Link to={`/releases/${card.id}`} data-testid={`release-board-link-${card.name}`}>
                <strong dir="ltr">{card.name}</strong>
              </Link>
              {card.release.stage_path === EMERGENCY_PATH && (
                <ToneTag tone="error" icon={<ThunderboltOutlined />}>
                  {t('releases.emergency')}
                </ToneTag>
              )}
            </Flex>
            <Typography.Text ellipsis={{ tooltip: card.release.subject }}>
              <bdi dir="auto">{card.release.subject}</bdi>
            </Typography.Text>
            <StatusTag status={card.release.status} catalogue={settings.data} />
          </Flex>
        )}
      />
      {moving && (
        <MoveDialog
          releaseId={moving.id}
          version={moving.version}
          move={moving.move}
          onClose={() => {
            setMoving(undefined);
          }}
        />
      )}
    </ListPage>
  );
}
