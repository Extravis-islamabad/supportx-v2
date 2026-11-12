import { Alert, Flex, Typography } from 'antd';

import { usePlanSections, type StageMove } from '@supportx/api-client';
import { EmptyText, RichTextView, WriteButton, useLabel } from '@supportx/ui';

const FAILED = 'deployment_failed';
const ROLLED_BACK = 'deployment_rolled_back';

/**
 * A failed deployment's guided path (REQ-REL-053 AC1): the failure is named on the release, its
 * backout plan is shown right there, and the release manager marks it rolled back through the
 * life cycle's own move (reason and all, in the move dialog). Shown only while it applies.
 */
export function ReleaseFailed({
  id,
  status,
  moves,
  onMove,
}: {
  id: string;
  status: string;
  moves: readonly StageMove[];
  onMove: (move: StageMove) => void;
}) {
  const t = useLabel();
  const failed = status === FAILED;
  const sections = usePlanSections(failed ? id : '');
  if (!failed) return null;
  const backout = (sections.data ?? []).find((s) => s.section === 'backout');
  const rollBack = moves.find((m) => m.to_status === ROLLED_BACK);
  return (
    <Alert
      type="error"
      showIcon
      style={{ marginBottom: 16 }}
      data-testid="release-failed"
      message={t('releases.failed.title')}
      description={
        <Flex vertical gap={8}>
          <Typography.Text strong>{t('releases.failed.backout')}</Typography.Text>
          {backout?.content ? (
            <RichTextView html={backout.content} testId="release-failed-backout" />
          ) : (
            <EmptyText>{t('releases.failed.no_backout')}</EmptyText>
          )}
          {rollBack !== undefined && (
            <div>
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
            </div>
          )}
        </Flex>
      }
    />
  );
}
