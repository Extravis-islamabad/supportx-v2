import { Button, Flex, List, Typography } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import { useAssetLinkedPage, type AssetLinkedSummary } from '@supportx/api-client';
import { Drawer, EmptyText, ToneTag, useDateTime, useLabel } from '@supportx/ui';

/** Where each kind of work item opens in the console. */
const PATHS: Record<string, string> = {
  incident: '/incidents',
  service_request: '/requests',
  problem: '/problems',
  change: '/changes',
  release: '/releases',
};

/**
 * The work items linked to an asset (WP-049b s4a; REQ-AST-044, D-158): per kind, how many are
 * still worked (open, paused, or resolved and not yet closed) and how many in all, counting only
 * the records you may see. Each counter opens their list. Shown only once work items offer the
 * links (lane A's port); live through the asset's channel (`fields`: linked).
 */
export function LinkedRecordsPanel({
  assetId,
  summary,
}: {
  assetId: string;
  summary: AssetLinkedSummary;
}) {
  const t = useLabel();
  const [kind, setKind] = useState<string>();
  // A kind with nothing linked is no news ("0 … of 0", QA 2026-11-12 F-14): only kinds with
  // records are listed, and none at all says so plainly.
  const kinds = summary.kinds.filter((k) => k.total > 0);
  if (kinds.length === 0) {
    return (
      <span data-testid="asset-linked-none">
        <EmptyText>{t('assets.linked.none')}</EmptyText>
      </span>
    );
  }
  return (
    <>
      <Flex vertical gap={4} data-testid="asset-linked">
        {kinds.map((k) => (
          <Button
            key={k.kind}
            type="text"
            onClick={() => {
              setKind(k.kind);
            }}
            style={{ justifyContent: 'space-between', display: 'flex', paddingInline: 4 }}
            data-testid={`asset-linked-${k.kind}`}
          >
            <span>{t(`work_item_type.${k.kind}`)}</span>
            <Typography.Text type="secondary">
              {t('assets.linked.counts', { worked: k.still_worked, total: k.total })}
            </Typography.Text>
          </Button>
        ))}
      </Flex>
      <LinkedDrawer
        assetId={assetId}
        kind={kind}
        onClose={() => {
          setKind(undefined);
        }}
      />
    </>
  );
}

function LinkedDrawer({
  assetId,
  kind,
  onClose,
}: {
  assetId: string;
  kind: string | undefined;
  onClose: () => void;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const page = useAssetLinkedPage(assetId, kind);
  const rows = page.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <Drawer
      open={kind !== undefined}
      onClose={onClose}
      // Never wider than a phone's screen (the visual matrix's 390 px).
      width="min(460px, 100vw)"
      title={kind === undefined ? '' : t(`work_item_type.${kind}`)}
      data-testid="asset-linked-drawer"
    >
      <List
        loading={page.isPending}
        dataSource={rows}
        locale={{ emptyText: <EmptyText>{t('assets.linked.none_visible')}</EmptyText> }}
        renderItem={(row) => (
          <List.Item>
            <Flex vertical gap={2} style={{ minWidth: 0 }}>
              <Link to={`${PATHS[row.kind] ?? '/incidents'}/${row.id}`}>
                <bdi dir="ltr">{row.display_id}</bdi> <bdi dir="auto">{row.subject}</bdi>
              </Link>
              <Flex gap={8} align="center" wrap>
                <ToneTag tone={row.still_worked ? 'info' : 'default'}>
                  {t(row.still_worked ? 'assets.linked.still_worked' : 'assets.linked.done')}
                </ToneTag>
                <Typography.Text type="secondary">{dates.format(row.updated_at)}</Typography.Text>
              </Flex>
            </Flex>
          </List.Item>
        )}
      />
      {page.hasNextPage && (
        <Button
          onClick={() => {
            void page.fetchNextPage();
          }}
          loading={page.isFetchingNextPage}
        >
          {t('assets.admin.load_more')}
        </Button>
      )}
    </Drawer>
  );
}
