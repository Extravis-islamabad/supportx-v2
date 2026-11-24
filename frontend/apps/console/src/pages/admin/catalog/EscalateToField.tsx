import { Form, Select } from 'antd';

import { useLabel } from '@supportx/ui';

import { ESCALATE_TO, type EscalateTo } from './stages';

/**
 * Where a stage's approval goes after its last reminder (WP-047a S3a; REQ-SR-034, Essentials):
 * the backup, the approver's manager, the request's group or nobody. The approver keeps it too
 * (REQ-SR-036 AC2); with nobody there, it goes to the approval administrators.
 */
export function EscalateToField({
  value,
  onChange,
  testId,
}: {
  value: EscalateTo | undefined;
  onChange: (next: EscalateTo) => void;
  testId: string;
}) {
  const t = useLabel();
  return (
    <Form.Item
      label={t('catalog_admin.approval.escalate_to')}
      extra={t('catalog_admin.approval.escalate_to_help')}
      style={{ minWidth: 260 }}
    >
      <Select<EscalateTo>
        value={value ?? 'backup'}
        options={ESCALATE_TO.map((code) => ({
          value: code,
          label: t(`approval_escalate_to.${code}`),
        }))}
        onChange={onChange}
        aria-label={t('catalog_admin.approval.escalate_to')}
        data-testid={testId}
      />
    </Form.Item>
  );
}
