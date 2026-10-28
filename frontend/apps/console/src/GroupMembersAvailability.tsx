import { Card, List, Space, Typography } from 'antd';

import { useIncidentAssignees, useStructure } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

import { MemberAvailability } from './MemberAvailability';

/**
 * A group's members with their availability: the lead (or an admin) sets a sick technician
 * Away so they stop receiving auto-assigned work (QA WP-029 follow-up).
 */
export function GroupMembersAvailability({
  groupId,
  canSet,
}: {
  groupId: string;
  canSet: boolean;
}) {
  const t = useLabel();
  const members = useIncidentAssignees(groupId, '');
  return (
    <List
      size="small"
      loading={members.isPending}
      dataSource={members.data ?? []}
      locale={{ emptyText: t('availability.no_members') }}
      data-testid={`group-members-${groupId}`}
      renderItem={(member) => (
        <List.Item data-testid={`group-member-${member.id}`}>
          <Typography.Text>
            <bdi>{member.display_name}</bdi>
          </Typography.Text>
          <MemberAvailability userId={member.id} canSet={canSet} />
        </List.Item>
      )}
    />
  );
}

/** On My profile: the groups you lead, so you can set a member Away (QA WP-029 follow-up). */
export function LedGroupsCard({ userId }: { userId: string }) {
  const t = useLabel();
  const groups = useStructure('groups', true, true);
  const led = (groups.data ?? []).filter((g) => g.lead_id === userId && !g.disabled);
  if (led.length === 0) return null;
  return (
    <Card title={t('availability.led_groups')} data-testid="led-groups-card">
      <Space direction="vertical" style={{ width: '100%' }}>
        <Typography.Text type="secondary">{t('availability.led_groups_help')}</Typography.Text>
        {led.map((group) => (
          <div key={group.id}>
            <Typography.Text strong>
              <bdi>{group.name}</bdi>
            </Typography.Text>
            <GroupMembersAvailability groupId={group.id} canSet />
          </div>
        ))}
      </Space>
    </Card>
  );
}
