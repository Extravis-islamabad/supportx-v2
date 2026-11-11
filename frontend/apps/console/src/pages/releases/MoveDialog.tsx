import type { StageMove } from '@supportx/api-client';

import { StagedMoveDialog } from '../staged/MoveDialog';

/**
 * A release's move dialog: the staged types' shared one (lane C and lane A, the change screens),
 * with the release's people, lists and fields. Props as before, so the release page is unchanged.
 */
export function MoveDialog({
  releaseId,
  version,
  move,
  onClose,
}: {
  releaseId: string;
  version: number;
  move: StageMove;
  onClose: () => void;
}) {
  return (
    <StagedMoveDialog
      path="releases"
      recordId={releaseId}
      version={version}
      move={move}
      onClose={onClose}
    />
  );
}
