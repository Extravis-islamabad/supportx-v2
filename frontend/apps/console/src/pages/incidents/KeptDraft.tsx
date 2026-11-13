import { Alert, App, Button, Space } from 'antd';
import type { FieldValues, UseFormReturn } from '@supportx/forms';

import { useDateTime, useLabel } from '@supportx/ui';

import type { useServerDraft } from './useServerDraft';

/** The note above the first field: a kept draft, with Restore (if readable) and Discard. */
export function KeptDraftNotice<T extends FieldValues>({
  form,
  draft,
  onRestore,
  onDiscard,
}: {
  form: UseFormReturn<T>;
  draft: ReturnType<typeof useServerDraft<T>>;
  onRestore: (values: Record<string, unknown>) => void;
  onDiscard: () => void;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const { modal } = App.useApp();
  // Read while rendering: react-hook-form keeps isDirty current only for a reader (the person
  // typed since the form opened; a template's own values are not typing).
  const typed = form.formState.isDirty;
  const kept = draft.pending;
  if (kept === null) return null;
  const when = (
    <time dateTime={kept.updated_at} title={dates.format(kept.updated_at)}>
      {dates.relative(kept.updated_at)}
    </time>
  );
  const discardButton = (
    <Button
      size="small"
      onClick={() => {
        draft.discard(onDiscard);
      }}
      data-testid="kept-draft-discard"
    >
      {t('kept_draft.discard')}
    </Button>
  );
  if (kept.unreadable || kept.values === null) {
    return (
      <Alert
        type="warning"
        showIcon
        role="status"
        message={t('kept_draft.unreadable')}
        action={discardButton}
        data-testid="kept-draft-unreadable"
      />
    );
  }
  const values = kept.values;
  const restore = () => {
    draft.restored();
    onRestore(values);
  };
  return (
    <Alert
      type="info"
      showIcon
      role="status"
      message={
        <span>
          {t('kept_draft.found_before')} {when}
        </span>
      }
      action={
        <Space>
          <Button
            size="small"
            type="primary"
            onClick={() => {
              if (!typed) {
                restore();
                return;
              }
              // Typing already started: never replaced without asking (lane C).
              modal.confirm({
                title: t('kept_draft.replace_title'),
                content: t('kept_draft.replace_body'),
                okText: t('kept_draft.restore'),
                cancelText: t('actions.cancel'),
                onOk: restore,
              });
            }}
            data-testid="kept-draft-restore"
          >
            {t('kept_draft.restore')}
          </Button>
          {discardButton}
        </Space>
      }
      data-testid="kept-draft"
    />
  );
}
