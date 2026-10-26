import { CloseOutlined, EyeInvisibleOutlined, EyeOutlined } from '@ant-design/icons';
import {
  App,
  Button,
  Card,
  Flex,
  List,
  Popconfirm,
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import { useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router';

import {
  fetchMentionable,
  useFollowerChange,
  useIncidentFollowers,
  type Incident,
  type Mentionable,
} from '@supportx/api-client';
import { EmptyText, reportError, ToneTag, useLabel, WriteButton } from '@supportx/ui';

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
  const button = (
    <WriteButton
      icon={following ? <EyeInvisibleOutlined /> : <EyeOutlined />}
      loading={change.isPending}
      onClick={onlyThroughFollowing ? undefined : toggle}
      aria-pressed={following}
      data-testid="inc-follow"
    >
      {t(following ? 'followers.unfollow' : 'followers.follow')}
    </WriteButton>
  );
  // Unfollowing what you see only by following it removes your access: ask first (QA BUG-09).
  return onlyThroughFollowing ? (
    <Popconfirm
      title={t('followers.unfollow')}
      description={t('followers.unfollow_loses_access')}
      okText={t('followers.unfollow')}
      okButtonProps={{ danger: true }}
      cancelText={t('actions.cancel')}
      onConfirm={toggle}
    >
      {button}
    </Popconfirm>
  ) : (
    button
  );
}

/** Who follows the incident and why; add (manage_followers) or remove people. */
export function FollowersCard({ item, me }: { item: Incident; me: string | null }) {
  const t = useLabel();
  const followers = useIncidentFollowers(item.id);
  const change = useFollowerChange(item.id);
  const [search, setSearch] = useState<Mentionable[]>([]);
  // Only the answer to the latest search counts: a slow earlier one (the empty search sent on
  // focus) must not replace the results of what was typed (QA BUG-08).
  const asked = useRef(0);
  const lookUp = (text: string) => {
    asked.current += 1;
    const ticket = asked.current;
    void fetchMentionable(item.id, text).then((found) => {
      if (ticket === asked.current) setSearch(found);
    });
  };
  const remove = (userId: string) => {
    change.mutate({ userId, follow: false }, { onError: reportError });
  };
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
                    <RemoveFollower
                      key="remove"
                      name={people[follower.user_id]?.display_name ?? ''}
                      self={follower.user_id === me}
                      losesAccess={follower.grants_access}
                      onRemove={() => {
                        remove(follower.user_id);
                      }}
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
                    <span>
                      <ToneTag tone="info">{t('followers.access')}</ToneTag>
                    </span>
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
            onSearch={lookUp}
            onFocus={() => {
              lookUp('');
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

/**
 * The X beside a follower. Someone who sees the incident only by following it loses access when
 * removed, so that asks first (QA BUG-09); removing anyone else is immediate.
 */
function RemoveFollower({
  name,
  self,
  losesAccess,
  onRemove,
}: {
  name: string;
  self: boolean;
  losesAccess: boolean;
  onRemove: () => void;
}): ReactNode {
  const t = useLabel();
  const button = (
    <Button
      size="small"
      type="text"
      icon={<CloseOutlined />}
      aria-label={t(self ? 'followers.unfollow' : 'followers.remove', { name })}
      onClick={losesAccess ? undefined : onRemove}
      data-testid="inc-follower-remove"
    />
  );
  if (!losesAccess) return button;
  return (
    <Popconfirm
      title={t(self ? 'followers.unfollow' : 'followers.remove', { name })}
      description={t(self ? 'followers.unfollow_loses_access' : 'followers.remove_loses_access', {
        name,
      })}
      okText={t('followers.remove_ok')}
      okButtonProps={{ danger: true }}
      cancelText={t('actions.cancel')}
      onConfirm={onRemove}
    >
      {button}
    </Popconfirm>
  );
}
