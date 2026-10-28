import { Flex, Switch, Tag, Typography } from 'antd';

import { useAvailability, useAvailabilityHistory, useSetAvailability } from '@supportx/api-client';
import { reportError, useDateTime, useLabel } from '@supportx/ui';

/**
 * Someone's Available / Away state as others see it: who set it and when ("Set Away by Amal
 * Admin at 10:32"), with a switch for those who may change it (their group's lead, an admin;
 * the server checks). A sick technician stops getting auto-assigned work (QA WP-029 follow-up).
 */
export function MemberAvailability({
  userId,
  canSet,
  showHistory = false,
}: {
  userId: string;
  canSet: boolean;
  showHistory?: boolean;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const states = useAvailability([userId]);
  const history = useAvailabilityHistory(userId, showHistory);
  const set = useSetAvailability();
  const current = states.data?.find((s) => s.user_id === userId);
  const available = (current?.state ?? 'available') === 'available';
  const setBy =
    current?.changed_by != null && current.changed_at != null
      ? t(available ? 'availability.set_available_by' : 'availability.set_away_by', {
          name: current.changed_by,
          time: dates.format(current.changed_at),
        })
      : null;
  return (
    <Flex vertical gap={4} data-testid={`member-availability-${userId}`}>
      <Flex gap={8} align="center" wrap>
        {canSet ? (
          <Switch
            checked={available}
            loading={set.isPending}
            checkedChildren={t('availability.available')}
            unCheckedChildren={t('availability.away')}
            aria-label={t('availability.member_label')}
            onChange={(next) => {
              set.mutate({ userId, state: next ? 'available' : 'away' }, { onError: reportError });
            }}
            data-testid={`member-availability-switch-${userId}`}
          />
        ) : (
          <Tag color={available ? 'success' : 'warning'}>
            {t(available ? 'availability.available' : 'availability.away')}
          </Tag>
        )}
        {setBy !== null && (
          <Typography.Text type="secondary" data-testid={`member-availability-by-${userId}`}>
            {setBy}
          </Typography.Text>
        )}
      </Flex>
      {showHistory && (history.data?.length ?? 0) > 1 && (
        <ul style={{ margin: 0, paddingInlineStart: 20 }} data-testid="member-availability-history">
          {(history.data ?? []).slice(1, 6).map((change, index) => (
            // Changes have no ID; newest first, as the server sends them.
            <li key={index}>
              <Typography.Text type="secondary">
                {t(
                  change.state === 'available'
                    ? 'availability.set_available_by'
                    : 'availability.set_away_by',
                  {
                    name: change.changed_by ?? t('automation.someone'),
                    time: change.changed_at === null ? '' : dates.format(change.changed_at),
                  },
                )}
              </Typography.Text>
            </li>
          ))}
        </ul>
      )}
    </Flex>
  );
}
