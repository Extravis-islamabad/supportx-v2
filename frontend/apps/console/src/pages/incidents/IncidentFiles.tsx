import { useQueryClient } from '@tanstack/react-query';
import { Typography } from 'antd';

import { queryKeys, useRecordFiles, type Incident } from '@supportx/api-client';
import { Attachments, useAccess, useLabel } from '@supportx/ui';

/**
 * The incident's own attachments (REQ-INC-079), under the description: files attached to the
 * record itself. Replies and notes show theirs on their own cards (IncidentConversation).
 */
export function IncidentFiles({
  item,
  canEdit,
  recordType = 'incident',
}: {
  item: Incident;
  canEdit: boolean;
  /** The files API's name of the record's type (a change's files too, REQ-CHG-100). */
  recordType?: string;
}) {
  const t = useLabel();
  const { can } = useAccess();
  const queryClient = useQueryClient();
  const found = useRecordFiles(recordType, item.id);
  const files = (found.data ?? []).filter(
    (file) => file.owner_type === 'work_item' && !file.inline,
  );
  return (
    <section aria-labelledby="inc-files-title" data-testid="inc-files">
      <Typography.Title level={3} id="inc-files-title" style={{ fontSize: 16, marginTop: 16 }}>
        {t('files.title')}
      </Typography.Title>
      {files.length === 0 && !canEdit && (
        <Typography.Text type="secondary">{t('files.empty')}</Typography.Text>
      )}
      <Attachments
        files={files}
        target={canEdit ? { ownerType: 'work_item', ownerId: item.id } : null}
        onStored={() => {
          void queryClient.invalidateQueries({
            queryKey: queryKeys.files.record(recordType, item.id),
          });
        }}
        canRemove={canEdit}
        canRescan={can('files.manage')}
        testId="inc-attachments"
      />
    </section>
  );
}
