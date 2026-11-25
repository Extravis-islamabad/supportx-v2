import { Button, Flex, List, Typography } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import { useCiLinkedPage, type CiLinkedKinds } from '@supportx/api-client';
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
 * The work items linked to a CI (WP-053 S5c; REQ-CMDB-019, D-158): per type, how many are open
 * and how many in all, counting only the records you may see, never a hint of the others. Each
 * type opens its list. Shown only once work items offer the links; live through the CI's
 * channel (`fields`: linked).
 */
export function AssociationsTab({ ciId, summary }: { ciId: string; summary: CiLinkedKinds }) {
  const t = useLabel();
  const [kind, setKind] = useState<string>();
  const kinds = summary.kinds.filter((k) => k.total > 0);
  return (
    <Flex vertical gap={8} data-testid="ci-associations">
      <Typography.Text type="secondary">{t('cmdb.linked.hint')}</Typography.Text>
      {kinds.length === 0 ? (
        <span data-testid="ci-associations-none">
          <EmptyText>{t('cmdb.linked.none')}</EmptyText>
        </span>
      ) : (
        <Flex vertical gap={4}>
          {kinds.map((k) => (
            <Button
              key={k.kind}
              type="text"
              onClick={() => {
                setKind(k.kind);
              }}
              style={{ justifyContent: 'space-between', display: 'flex', paddingInline: 4 }}
              data-testid={`ci-associations-${k.kind}`}
            >
              <span>{t(`work_item_type.${k.kind}`)}</span>
              <Typography.Text type="secondary">
                {t('cmdb.linked.counts', { open: k.open, total: k.total })}
              </Typography.Text>
            </Button>
          ))}
        </Flex>
      )}
      <LinkedDrawer
        ciId={ciId}
        kind={kind}
        onClose={() => {
          setKind(undefined);
        }}
      />
    </Flex>
  );
}

function LinkedDrawer({
  ciId,
  kind,
  onClose,
}: {
  ciId: string;
  kind: string | undefined;
  onClose: () => void;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const page = useCiLinkedPage(ciId, kind);
  const rows = page.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <Drawer
      open={kind !== undefined}
      onClose={onClose}
      // Never wider than a phone's screen (the visual matrix's 390 px).
      width="min(460px, 100vw)"
      title={kind === undefined ? '' : t(`work_item_type.${kind}`)}
      data-testid="ci-associations-drawer"
    >
      <List
        loading={page.isPending}
        dataSource={rows}
        locale={{ emptyText: <EmptyText>{t('cmdb.linked.none_visible')}</EmptyText> }}
        renderItem={(row) => (
          <List.Item>
            <Flex vertical gap={2} style={{ minWidth: 0 }}>
              <Link to={`${PATHS[row.kind] ?? '/incidents'}/${row.id}`}>
                <bdi dir="ltr">{row.display_id}</bdi> <bdi dir="auto">{row.subject}</bdi>
              </Link>
              <Flex gap={8} align="center" wrap>
                <ToneTag tone={row.open ? 'info' : 'default'}>
                  {t(row.open ? 'cmdb.linked.open' : 'cmdb.linked.done')}
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
          {t('cmdb.linked.load_more')}
        </Button>
      )}
    </Drawer>
  );
}
