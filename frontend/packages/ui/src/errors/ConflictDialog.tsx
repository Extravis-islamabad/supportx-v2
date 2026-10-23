import { Modal, Typography } from 'antd';

import { useLabel } from '../appearance';

export interface ConflictDialogProps {
  open: boolean;
  /** Discard my edits and show the latest saved version. */
  onReload: () => void;
  /** Load the latest version but keep my edits on top, then let me save again. */
  onKeepMine: () => void;
}

/** 409 version_conflict: someone saved this record after it was opened (CLAUDE.md rule g). */
export function ConflictDialog({ open, onReload, onKeepMine }: ConflictDialogProps) {
  const t = useLabel();
  return (
    <Modal
      open={open}
      title={t('conflict.title')}
      okText={t('conflict.keep_mine')}
      cancelText={t('conflict.reload')}
      onOk={onKeepMine}
      onCancel={onReload}
      closable={false}
      maskClosable={false}
      destroyOnHidden
    >
      <Typography.Paragraph>{t('conflict.body')}</Typography.Paragraph>
    </Modal>
  );
}
