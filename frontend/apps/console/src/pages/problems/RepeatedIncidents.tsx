import { Button, Card, Flex, List, Typography } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';

import {
  problemKeys,
  useHandleRepeatHit,
  useIncidentCategories,
  useRepeatHits,
  useUnits,
  type RepeatHit,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import { reportError, useAppearance, useDateTime, useLabel, WriteButton } from '@supportx/ui';

import { categoryPath } from '../incidents/labels';

const CHANGED = 'work_items.problem_repeats_changed';

/**
 * Sets of repeated incidents the rules found (WP-044c D16, REQ-PRB-068): for who may create
 * problems, one row per set with how many and where, "Create problem from these" (the new
 * problem form from its incidents, which then marks the set handled) and "Dismiss". Live: a new
 * set, or one handled elsewhere, shows at once. Hidden when there is none.
 */
export function RepeatedIncidents({ enabled }: { enabled: boolean }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { relative } = useDateTime();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const hits = useRepeatHits(enabled);
  const categories = useIncidentCategories(enabled);
  const sites = useUnits('sites');
  const handle = useHandleRepeatHit();
  useTenantChannel((message) => {
    if (message.type === CHANGED)
      void queryClient.invalidateQueries({ queryKey: problemKeys.repeats });
  });
  const rows = hits.data ?? [];
  if (!enabled || rows.length === 0) return null;
  const where = (hit: RepeatHit) => {
    const category = categoryPath(t, categories.data ?? [], hit.category_id, locale);
    const site = sites.data?.find((s) => s.id === hit.site_id)?.name;
    return site === undefined ? category : t('problems.repeats.where', { category, site });
  };
  return (
    <Card size="small" title={t('problems.repeats.title')} data-testid="prb-repeats">
      <List
        dataSource={rows}
        renderItem={(hit) => (
          <List.Item
            data-testid={`prb-repeat-${hit.id}`}
            actions={[
              <WriteButton
                key="create"
                type="link"
                onClick={() => void navigate(`/problems/new?repeat=${hit.id}`)}
                data-testid={`prb-repeat-create-${hit.id}`}
              >
                {t('problems.repeats.create')}
              </WriteButton>,
              <Button
                key="dismiss"
                type="link"
                loading={handle.isPending && handle.variables.hitId === hit.id}
                onClick={() => {
                  handle.mutate(
                    { hitId: hit.id, version: hit.version, outcome: 'dismissed' },
                    { onError: reportError },
                  );
                }}
                data-testid={`prb-repeat-dismiss-${hit.id}`}
              >
                {t('problems.repeats.dismiss')}
              </Button>,
            ]}
          >
            <Flex vertical gap={2}>
              <Typography.Text strong>
                {t('problems.repeats.count', { count: hit.incident_count })}
              </Typography.Text>
              <Typography.Text type="secondary">
                <bdi>{where(hit)}</bdi>
                {' · '}
                {t('problems.repeats.since', { when: relative(hit.first_at) })}
              </Typography.Text>
            </Flex>
          </List.Item>
        )}
      />
    </Card>
  );
}
