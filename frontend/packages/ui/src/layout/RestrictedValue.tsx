import { EyeInvisibleOutlined, LockOutlined } from '@ant-design/icons';
import { Typography } from 'antd';

import { useLabel } from '../appearance';
import { TYPE } from '../density';

import type { RestrictionKind } from './restriction';

/**
 * A value the person's roles withhold (ADR-047 §4): the server sends null and names the field in
 * `hidden_fields` or `masked_fields`; the page says so instead of showing a blank.
 *
 * Muted secondary text with an icon that carries no meaning of its own (aria-hidden): the words
 * say it, never a tooltip alone (lane C's slice c review).
 */
export function RestrictedValue({ kind, testId }: { kind: RestrictionKind; testId?: string }) {
  const t = useLabel();
  const Icon = kind === 'hidden' ? EyeInvisibleOutlined : LockOutlined;
  return (
    <Typography.Text
      type="secondary"
      style={{ fontSize: TYPE.data }}
      data-testid={testId ?? `restricted-${kind}`}
    >
      <Icon aria-hidden style={{ marginInlineEnd: 4 }} />
      {t(kind === 'hidden' ? 'layout.restricted_hidden' : 'layout.restricted_masked')}
    </Typography.Text>
  );
}
