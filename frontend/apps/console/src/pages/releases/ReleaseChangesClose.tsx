import { Button, Flex, List, Select, Typography } from 'antd';
import { useState } from 'react';

import {
  useCloseReleaseChanges,
  useReleaseChanges,
  useStagedSettings,
  type LinkedChangeClosed,
} from '@supportx/api-client';
import { reportError, useAppearance, useLabel } from '@supportx/ui';

import { labelled } from '../incidents/labels';
import { skipReason } from '../incidents/list/model';

const FINAL = new Set(['closed', 'canceled']);

/**
 * In a closing release's move dialog (REQ-REL-052): its changes not closed yet are open work,
 * and this offers to close the ones you may close, each by its own close with the code chosen
 * here. Each result shows: closed, or why not (never forced). Hidden when none is left to close.
 */
export function ReleaseChangesClose({ releaseId }: { releaseId: string }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const changes = useReleaseChanges(releaseId);
  const settings = useStagedSettings('changes');
  const close = useCloseReleaseChanges();
  const [code, setCode] = useState<string>();
  const [results, setResults] = useState<LinkedChangeClosed[] | null>(null);
  const open = (changes.data ?? []).filter(
    (c) => !c.visible || !FINAL.has(c.status_category ?? ''),
  );
  if (open.length === 0 && results === null) return null;
  // Worded as the bulk drawer words a skip (the same code, field and params).
  const reasonOf = (r: LinkedChangeClosed) =>
    skipReason(t, {
      id: r.id ?? '',
      display_id: r.display_id ?? null,
      outcome: 'skipped',
      code: r.code ?? null,
      field: r.field ?? null,
      params: r.params ?? undefined,
    });
  return (
    <Flex vertical gap={8} data-testid="release-close-changes">
      <Typography.Text strong>{t('releases.close_changes.title')}</Typography.Text>
      <Typography.Text type="secondary">{t('releases.close_changes.help')}</Typography.Text>
      <Flex gap={8} wrap align="center">
        <Select
          style={{ minWidth: 220 }}
          aria-label={t('work_item.field.closure_code')}
          placeholder={t('work_item.field.closure_code')}
          value={code}
          onChange={setCode}
          options={(settings.data?.closure_codes ?? [])
            .filter((c) => !c.disabled)
            .map((c) => ({
              value: c.code,
              label: labelled(c.labels, locale, () => t(`closure_code.${c.code}`)),
            }))}
          data-testid="release-close-changes-code"
        />
        <Button
          disabled={code === undefined}
          loading={close.isPending}
          onClick={() => {
            if (code === undefined) return;
            close.mutate(
              { id: releaseId, closureCode: code },
              { onSuccess: setResults, onError: reportError },
            );
          }}
          data-testid="release-close-changes-run"
        >
          {t('releases.close_changes.run')}
        </Button>
      </Flex>
      {results !== null && (
        <List
          size="small"
          data-testid="release-close-changes-results"
          dataSource={results}
          locale={{ emptyText: t('releases.close_changes.none') }}
          renderItem={(r, index) => (
            <List.Item key={r.id ?? `hidden-${String(index)}`}>
              <Flex gap={8} wrap>
                <bdi dir="ltr">{r.display_id ?? t('releases.close_changes.hidden')}</bdi>
                <Typography.Text type={r.closed ? 'success' : 'secondary'}>
                  {r.closed ? t('releases.close_changes.closed') : reasonOf(r)}
                </Typography.Text>
              </Flex>
            </List.Item>
          )}
        />
      )}
    </Flex>
  );
}
