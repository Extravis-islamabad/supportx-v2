import { Alert, Flex, Typography } from 'antd';

import { useReleaseChanges, useRemoveReleaseChange } from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { WriteButton, reportError, useAccess, useLabel } from '@supportx/ui';

const CANCELED = 'closure_canceled';

/**
 * A canceled release's changes (REQ-REL-054): they are never canceled with it, and stay linked
 * until someone unlinks them; while any are linked, the release offers to do that in one go
 * (each unlink is the release's own, with history on both records). Gone once none are left.
 */
export function ReleaseCanceled({ id, status }: { id: string; status: string }) {
  const t = useLabel();
  const { can } = useAccess();
  const list = useListFormat();
  const canceled = status === CANCELED;
  const changes = useReleaseChanges(canceled ? id : '');
  const remove = useRemoveReleaseChange();
  // Only the changes you may see: a hidden one is neither named nor unlinked from here.
  const linked = (changes.data ?? []).filter((c) => c.visible);
  if (!canceled || linked.length === 0) return null;
  const unlinkAll = () => {
    for (const change of linked) {
      remove.mutate({ id, changeId: change.id }, { onError: reportError });
    }
  };
  return (
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 16 }}
      data-testid="release-canceled-changes"
      message={t('releases.canceled.changes_title', { count: linked.length })}
      description={
        <Flex vertical gap={8}>
          <Typography.Text>{t('releases.canceled.changes_help')}</Typography.Text>
          <bdi dir="auto">
            {list(linked.map((c) => [c.display_id ?? '', c.subject ?? ''].join(' ').trim()))}
          </bdi>
          {can('releases.edit') && (
            <div>
              <WriteButton
                loading={remove.isPending}
                onClick={unlinkAll}
                data-testid="release-unlink-changes"
              >
                {t('releases.canceled.unlink')}
              </WriteButton>
            </div>
          )}
        </Flex>
      }
    />
  );
}
