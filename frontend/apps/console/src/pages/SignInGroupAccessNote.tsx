import { Alert, Flex, Typography } from 'antd';

import { useMyAccessElsewhere, type HeldElsewhere } from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { useLabel } from '@supportx/ui';

import { roleName } from './admin/roleName';

/** Each provider's items, in the order the server gave them (by kind, then name). */
function byProvider(items: HeldElsewhere[]): [string, HeldElsewhere[]][] {
  const found = new Map<string, HeldElsewhere[]>();
  for (const item of items) {
    found.set(item.provider_name, [...(found.get(item.provider_name) ?? []), item]);
  }
  return [...found.entries()];
}

/**
 * D-188 (WP-057 S5c-1b): access a sign-in group gives you that this session leaves out, and the
 * sign-in it applies through. Nothing is shown when there is none. Live with the person's access.
 */
export function SignInGroupAccessNote() {
  const t = useLabel();
  const listFormat = useListFormat();
  const found = useMyAccessElsewhere();
  const items = found.data ?? [];
  if (items.length === 0) return null;
  const named = (item: HeldElsewhere) =>
    item.kind === 'role'
      ? roleName({ key: item.role_key ?? '', name: item.name, is_system: item.is_system }, t)
      : item.name;
  return (
    <Alert
      type="info"
      showIcon
      data-testid="profile-sign-in-group-access"
      message={t('profile.sign_in_group.title')}
      description={
        <Flex vertical gap={8}>
          {byProvider(items).map(([provider, held]) => (
            <Typography.Paragraph key={provider} style={{ margin: 0 }}>
              {t('profile.sign_in_group.note', { provider })}{' '}
              <Typography.Text strong>{listFormat(held.map(named), 'conjunction')}</Typography.Text>
            </Typography.Paragraph>
          ))}
        </Flex>
      }
    />
  );
}
