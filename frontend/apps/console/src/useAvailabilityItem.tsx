import { Flex, Grid, Switch, type MenuProps } from 'antd';

import { useAvailability, useSetAvailability } from '@supportx/api-client';
import { reportError, useLabel } from '@supportx/ui';

type Item = NonNullable<MenuProps['items']>[number];

/**
 * Available / Away in the user menu below 1200 px, where the header has no room for the
 * switch (WP-029, REQ-ASG-006): one tap away at every width. None when `enabled` is false.
 */
export function useAvailabilityItem(userId: string, enabled: boolean): Item[] {
  const t = useLabel();
  const narrow = Grid.useBreakpoint().xl !== true;
  const shown = enabled && narrow;
  const current = useAvailability([userId], shown);
  const set = useSetAvailability();
  if (!shown) return [];
  const available =
    (current.data?.find((a) => a.user_id === userId)?.state ?? 'available') === 'available';
  return [
    {
      key: 'availability',
      label: (
        <Flex justify="space-between" align="center" gap={12} data-testid="availability-menu-item">
          {t('automation.availability.label')}
          <Switch
            size="small"
            checked={available}
            loading={current.isPending || set.isPending}
            checkedChildren={t('availability.available')}
            unCheckedChildren={t('availability.away')}
            aria-label={t('automation.availability.label')}
          />
        </Flex>
      ),
      onClick: () => {
        set.mutate({ userId, state: available ? 'away' : 'available' }, { onError: reportError });
      },
    },
  ];
}
