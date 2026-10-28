import { Modal, Typography } from 'antd';

import { useListFormat } from '@supportx/labels';

import { useAppearance, useLabel } from '../appearance';
import { explain } from './conflictDetails';

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
  /**
   * The record as the user opened it and as it is now (live). When the server cannot say which
   * fields changed (a record without field history), the dialog compares the two (QA WP-029
   * BUG-05). Pass both from every editor.
   */
  opened?: object;
  latest?: object;
}

/** 409 version_conflict: someone saved this record after it was opened (CLAUDE.md rule g). */
export function ConflictDialog({
  open,
  onReload,
  onKeepMine,
  error,
  fieldLabel,
  opened,
  latest,
}: ConflictDialogProps) {
  const t = useLabel();
  const list = useListFormat();
  const { locale } = useAppearance();
  const found = explain(error, opened, latest);
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
          {found.by !== '' &&
            (when === null
              ? t('conflict.changed_by', { name: found.by })
              : t('conflict.changed_by_at', { name: found.by, time: when }))}
          {found.fields.length > 0 && (
            <>
              {' '}
              {t('conflict.changed_fields', {
                // Several codes can share a name (a status's name and colour): each name once.
                fields: list([...new Set(found.fields.map(name))], 'conjunction'),
              })}
            </>
          )}
        </Typography.Paragraph>
      )}
      <Typography.Paragraph>{t('conflict.body')}</Typography.Paragraph>
    </Modal>
  );
}
