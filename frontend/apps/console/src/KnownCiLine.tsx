import { Form, Typography } from 'antd';

import { useLabel } from '@supportx/ui';

/**
 * The CI a create form was raised from (`?ci=`), read-only: its name, never its ID (rule d).
 * Nothing at all when the CI is unknown, unseen or the plan has no CMDB.
 */
export function KnownCiLine({ name }: { name: string | undefined }) {
  const t = useLabel();
  if (name === undefined) return null;
  return (
    <Form.Item label={t('work_item.field.raised_from_ci')}>
      <Typography.Text data-testid="raised-from-ci">{name}</Typography.Text>
    </Form.Item>
  );
}
