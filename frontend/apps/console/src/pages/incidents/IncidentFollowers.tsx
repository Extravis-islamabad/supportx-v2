import { CloseOutlined, EyeInvisibleOutlined, EyeOutlined } from '@ant-design/icons';
import { App, Button, Card, Flex, List, Select, Space, Tag, Tooltip, Typography } from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import {
  fetchMentionable,
  useFollowerChange,
  useIncidentFollowers,
  type Incident,
  type Mentionable,
} from '@supportx/api-client';
import { EmptyText, reportError, useLabel, WriteButton } from '@supportx/ui';

/**
 * Follow or unfollow this incident (REQ-INC-056/151). Someone who follows only because they
 * handed it over (D-068) loses sight of it when they unfollow: the button says so, and the page
 * goes back to the list afterwards.
 */
export function FollowButton({ item, me }: { item: Incident; me: string | null }) {
  const t = useLabel();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const followers = useIncidentFollowers(item.id);
  const change = useFollowerChange(item.id);
  const mine = followers.data?.items.find((f) => f.user_id === me);
  if (me === null) return null;
  const following = item.following || mine !== undefined;
  const onlyThroughFollowing = mine?.grants_access === true;
  const toggle = () => {
    change.mutate(
      { userId: me, follow: !following },
      {
        onSuccess: (found) => {
          void message.success(t(following ? 'followers.unfollowed' : 'followers.followed'));
          if (following && onlyThroughFollowing && found.items.length === 0) {
            void navigate('/incidents');
          }
        },
        onError: reportError,
      },
    );
  };
  return (
    <Tooltip title={onlyThroughFollowing ? t('followers.unfollow_loses_access') : undefined}>
      <WriteButton
        icon={following ? <EyeInvisibleOutlined /> : <EyeOutlined />}
        loading={change.isPending}
        onClick={toggle}
        aria-pressed={following}
        data-testid="inc-follow"
      >
        {t(following ? 'followers.unfollow' : 'followers.follow')}
      </WriteButton>
    </Tooltip>
  );
}

/** Who follows the incident and why; add (manage_followers) or remove people. */
export function FollowersCard({ item, me }: { item: Incident; me: string | null }) {
  const t = useLabel();
  const followers = useIncidentFollowers(item.id);
  const change = useFollowerChange(item.id);
  const [search, setSearch] = useState<Mentionable[]>([]);
  const data = followers.data;
  const people = data?.people ?? {};
  return (
    <Card
      size="small"
      title={t('followers.title', { count: data?.items.length ?? 0 })}
      data-testid="inc-followers"
    >
      <List
        size="small"
        loading={followers.isPending}
        dataSource={data?.items ?? []}
        locale={{ emptyText: <EmptyText>{t('followers.none')}</EmptyText> }}
        renderItem={(follower) => (
          <List.Item
            data-testid="inc-follower"
            actions={
              follower.removable
                ? [
                    <Button
                      key="remove"
                      size="small"
                      type="text"
                      icon={<CloseOutlined />}
                      aria-label={t(
                        follower.user_id === me ? 'followers.unfollow' : 'followers.remove',
                        { name: people[follower.user_id]?.display_name ?? '' },
                      )}
                      onClick={() => {
                        change.mutate(
                          { userId: follower.user_id, follow: false },
                          { onError: reportError },
                        );
                      }}
                      data-testid="inc-follower-remove"
                    />,
                  ]
                : []
            }
          >
            <Space direction="vertical" size={0}>
              <Typography.Text>
                <bdi dir="auto">{people[follower.user_id]?.display_name ?? ''}</bdi>
                {follower.user_id === me ? ` ${t('followers.you')}` : ''}
              </Typography.Text>
              <Space size={4} wrap>
                <Tag>{t(`follow_reason.${follower.reason}`)}</Tag>
                {follower.grants_access && (
                  <Tooltip title={t('followers.access_hint')}>
                    <Tag color="blue">{t('followers.access')}</Tag>
                  </Tooltip>
                )}
              </Space>
            </Space>
          </List.Item>
        )}
      />
      {data?.may_manage === true && (
        <Flex style={{ marginTop: 8 }}>
          <Select<string>
            showSearch
            value={null}
            placeholder={t('followers.add')}
            aria-label={t('followers.add')}
            filterOption={false}
            style={{ width: '100%' }}
            onSearch={(text) => {
              void fetchMentionable(item.id, text).then(setSearch);
            }}
            onFocus={() => {
              void fetchMentionable(item.id, '').then(setSearch);
            }}
            onChange={(userId) => {
              change.mutate({ userId, follow: true }, { onError: reportError });
            }}
            options={search.map((p) => ({
              value: p.id,
              disabled: !p.can_see,
              label: (
                <Flex justify="space-between" gap={8}>
                  <span>
                    <bdi dir="auto">{p.display_name}</bdi>{' '}
                    <Typography.Text type="secondary">{p.email}</Typography.Text>
                  </span>
                  {!p.can_see && <Tag>{t('richtext.mention_cannot_see')}</Tag>}
                </Flex>
              ),
            }))}
            data-testid="inc-follower-add"
          />
        </Flex>
      )}
    </Card>
  );
}
