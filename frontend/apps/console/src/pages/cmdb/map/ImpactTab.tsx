import { useQueryClient } from '@tanstack/react-query';
import { Alert, Card, Empty, Flex, List, Segmented, Select, Skeleton, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { Link } from 'react-router';

import {
  queryKeys,
  useCiImpact,
  type CiImpact,
  type CiImpactNode,
  type ImpactDirection,
} from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import { ToneTag, useAppearance, useLabel } from '@supportx/ui';

import { nodeLook, nodeName, nodeType } from './words';

const DIRECTIONS: readonly ImpactDirection[] = ['dependents', 'dependencies', 'both'];
const DEPTH_DEFAULT = 3;
const DEPTH_MAX = 10;

/**
 * The CI's Impact tab (template A; REQ-CMDB-010, 030): what a failure of this CI reaches, or
 * what it relies on, to a chosen depth. The walk goes through CIs the reader can't see, so a
 * path stays true; those show as "A CI you can't open", with nothing else about them.
 *
 * Live (§8.3): one CMDB list channel, as the map; a message touching a shown CI, or asking for
 * a refresh, refetches the answer (the reconcile, never a patched guess).
 */
export function ImpactTab({ ciId }: { ciId: string }) {
  const t = useLabel();
  const [direction, setDirection] = useState<ImpactDirection>('dependents');
  const [depth, setDepth] = useState(DEPTH_DEFAULT);
  const found = useCiImpact(ciId, direction, depth);
  const queryClient = useQueryClient();
  const shown = useMemo(() => {
    const ids = new Set<string>([ciId]);
    for (const node of found.data?.cis ?? []) if (!node.restricted) ids.add(node.key);
    return ids;
  }, [ciId, found.data]);
  useListChannel('cmdb', (message) => {
    if (message.refresh === true || message.ids.some((id) => shown.has(id))) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.impactOf(ciId) });
    }
  });
  return (
    <Flex vertical gap={16} data-testid="ci-impact-tab">
      <Flex gap={12} wrap align="center">
        <Segmented<ImpactDirection>
          value={direction}
          onChange={setDirection}
          options={DIRECTIONS.map((value) => ({
            value,
            label: t(`cmdb_impact_direction.${value}`),
          }))}
          data-testid="ci-impact-direction"
        />
        <Flex gap={8} align="center">
          <Typography.Text id="ci-impact-depth-label">{t('cmdb.impact.depth')}</Typography.Text>
          <Select<number>
            value={depth}
            onChange={setDepth}
            aria-labelledby="ci-impact-depth-label"
            style={{ minWidth: 96 }}
            options={Array.from({ length: DEPTH_MAX }, (_, i) => ({
              value: i + 1,
              label: String(i + 1),
            }))}
            data-testid="ci-impact-depth"
          />
        </Flex>
      </Flex>
      {found.isPending ? (
        <Skeleton active />
      ) : found.isError ? (
        <Alert type="error" showIcon message={t('cmdb.impact.load_failed')} />
      ) : (
        <ImpactBody impact={found.data} />
      )}
    </Flex>
  );
}

function ImpactBody({ impact }: { impact: CiImpact }) {
  const t = useLabel();
  const { locale } = useAppearance();
  // The key each node was reached from, by name, for the path ("via ...").
  const byKey = useMemo(() => {
    const names = new Map<string, CiImpactNode>([[impact.start.key, impact.start]]);
    for (const node of impact.cis) names.set(node.key, node);
    return names;
  }, [impact]);
  const levels = useMemo(() => {
    const grouped = new Map<number, CiImpactNode[]>();
    for (const node of impact.cis) {
      const depth = node.depth ?? 0;
      grouped.set(depth, [...(grouped.get(depth) ?? []), node]);
    }
    return [...grouped.entries()].sort(([a], [b]) => a - b);
  }, [impact.cis]);
  return (
    <Flex vertical gap={16}>
      {impact.truncated && (
        <Alert
          type="warning"
          showIcon
          message={t('cmdb.impact.truncated', { max: impact.ci_max })}
          data-testid="ci-impact-truncated"
        />
      )}
      <Flex gap={16} wrap data-testid="ci-impact-summary">
        <Summary label={t('cmdb.impact.services')} value={String(impact.services.length)} />
        <Summary label={t('cmdb.impact.cis')} value={String(impact.cis.length)} />
        {impact.restricted > 0 && (
          <Summary label={t('cmdb.impact.restricted')} value={String(impact.restricted)} />
        )}
        <Summary
          label={t('cmdb.impact.affected_users')}
          value={
            impact.affected_users == null
              ? t(`cmdb_impact_users_reason.${impact.affected_users_reason ?? 'not_configured'}`)
              : String(impact.affected_users)
          }
        />
      </Flex>
      {impact.cis.length === 0 ? (
        <Empty description={t('cmdb.impact.none')} data-testid="ci-impact-empty" />
      ) : (
        <>
          {impact.services.length > 0 && (
            <Card size="small" title={t('cmdb.impact.services')}>
              <List
                size="small"
                dataSource={impact.services}
                renderItem={(service) => (
                  <List.Item key={service.id}>
                    <Link to={`/cmdb/cis/${service.id}`}>{service.name}</Link>
                  </List.Item>
                )}
                data-testid="ci-impact-services"
              />
            </Card>
          )}
          {levels.map(([depth, nodes]) => (
            <Card
              key={depth}
              size="small"
              title={t('cmdb.impact.step', { step: depth, total: nodes.length })}
            >
              <List
                size="small"
                dataSource={nodes}
                renderItem={(node) => {
                  const via = node.via == null ? undefined : byKey.get(node.via);
                  const look = nodeLook(node);
                  return (
                    <List.Item key={node.key} data-testid="ci-impact-row">
                      <Flex vertical gap={2}>
                        {node.restricted || node.id == null ? (
                          <Typography.Text type="secondary">{nodeName(t, node)}</Typography.Text>
                        ) : (
                          <Flex gap={8} wrap align="center">
                            <Link to={`/cmdb/cis/${node.id}`}>{nodeName(t, node)}</Link>
                            <Typography.Text type="secondary">{node.display_id}</Typography.Text>
                            <ToneTag tone={look.tone}>{nodeType(t, locale, node)}</ToneTag>
                          </Flex>
                        )}
                        {via !== undefined && (
                          <Typography.Text type="secondary">
                            {t('cmdb.impact.via', { name: nodeName(t, via) })}
                          </Typography.Text>
                        )}
                      </Flex>
                    </List.Item>
                  );
                }}
              />
            </Card>
          ))}
        </>
      )}
    </Flex>
  );
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <Flex vertical>
      <Typography.Text type="secondary">{label}</Typography.Text>
      <Typography.Text strong>{value}</Typography.Text>
    </Flex>
  );
}
