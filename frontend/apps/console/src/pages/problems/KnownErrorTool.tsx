import { BulbOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Badge, Button, Dropdown } from 'antd';

import { queryKeys, useApplyKnownError, useKnownErrorSuggestions } from '@supportx/api-client';
import { reportError, useLabel } from '@supportx/ui';

/**
 * Known errors in the incident's editors (REQ-PRB-038). It suggests open known errors that
 * match the incident's words (only ones the technician may see, never a root cause). Choosing
 * one ("apply its workaround") links the incident to that problem and puts the workaround at
 * the caret. Nothing is sent: the technician reviews and sends it as usual.
 */
export function KnownErrorTool({
  incidentId,
  insert,
}: {
  incidentId: string;
  insert: (html: string) => void;
}) {
  const t = useLabel();
  const queryClient = useQueryClient();
  const found = useKnownErrorSuggestions(incidentId);
  const apply = useApplyKnownError(incidentId);
  const rows = found.data ?? [];
  if (rows.length === 0) return null;
  return (
    <Dropdown
      trigger={['click']}
      menu={{
        items: rows.map((k) => ({
          key: k.id,
          label: t('problems.known_error.apply', { id: k.display_id, subject: k.subject }),
          'data-testid': `inc-apply-workaround-${k.display_id}`,
        })),
        onClick: ({ key }) => {
          const chosen = rows.find((k) => k.id === key);
          if (chosen === undefined) return;
          apply.mutate(chosen.id, {
            onSuccess: () => {
              insert(chosen.workaround ?? '');
              void queryClient.invalidateQueries({
                queryKey: queryKeys.incidents.links(incidentId),
              });
            },
            onError: reportError,
          });
        },
      }}
    >
      <Badge count={rows.length} size="small">
        <Button
          size="small"
          type="text"
          icon={<BulbOutlined />}
          aria-label={t('problems.known_error.suggested', { count: rows.length })}
          data-testid="inc-known-error-tool"
        />
      </Badge>
    </Dropdown>
  );
}
