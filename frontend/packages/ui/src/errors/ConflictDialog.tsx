import { Modal, Typography } from 'antd';

import { ApiError } from '@supportx/api-client';

import { useAppearance, useLabel } from '../appearance';

export interface ConflictDialogProps {
  open: boolean;
  /** Discard my edits and show the latest saved version. */
  onReload: () => void;
  /** Load the latest version but keep my edits on top, then let me save again. */
  onKeepMine: () => void;
  /** The 409 itself: its params say who changed which fields, and when (WP-012). */
  error?: unknown;
  /** Display name of a changed field code (`title` → "Title"); default: the code's label. */
  fieldLabel?: (field: string) => string;
}

interface Explanation {
  by: string;
  at: string | null;
  fields: string[];
}

function explain(error: unknown): Explanation | null {
  if (!(error instanceof ApiError) || !error.isConflict) return null;
  const { changed_by: by, changed_at: at, changed_fields: fields } = error.params;
  if (typeof by !== 'string' || by === '') return null;
  return {
    by,
    at: typeof at === 'string' ? at : null,
    fields: typeof fields === 'string' && fields !== '' ? fields.split(',') : [],
  };
}

/** 409 version_conflict: someone saved this record after it was opened (CLAUDE.md rule g). */
export function ConflictDialog({
  open,
  onReload,
  onKeepMine,
  error,
  fieldLabel,
}: ConflictDialogProps) {
  const t = useLabel();
  const { locale } = useAppearance();
  const found = explain(error);
  const name = fieldLabel ?? ((field: string) => t(`field.${field}`));
  const when =
    found?.at == null
      ? null
      : new Intl.DateTimeFormat(locale, { timeStyle: 'short' }).format(new Date(found.at));
  return (
    <Modal
      open={open}
      title={t('conflict.title')}
      okText={t('conflict.keep_mine')}
      cancelText={t('conflict.reload')}
      onOk={onKeepMine}
      onCancel={onReload}
      okButtonProps={{ 'data-testid': 'conflict-keep-mine' }}
      cancelButtonProps={{ 'data-testid': 'conflict-reload' }}
      closable={false}
      maskClosable={false}
      destroyOnHidden
    >
      {found !== null && (
        <Typography.Paragraph data-testid="conflict-who">
          {when === null
            ? t('conflict.changed_by', { name: found.by })
            : t('conflict.changed_by_at', { name: found.by, time: when })}
          {found.fields.length > 0 && (
            <>
              {' '}
              {t('conflict.changed_fields', {
                fields: found.fields.map(name).join(t('list.separator')),
              })}
            </>
          )}
        </Typography.Paragraph>
      )}
      <Typography.Paragraph>{t('conflict.body')}</Typography.Paragraph>
    </Modal>
  );
}
