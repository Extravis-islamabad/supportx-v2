import { PlusOutlined } from '@ant-design/icons';
import { Button, Flex, Input, Select, Space } from 'antd';

import type { RuleFieldOut, TriggerActionIO } from '@supportx/api-client';
import { lengthLimit, useLabel } from '@supportx/ui';

import { ValueInput } from './fields';
import { emptyAction, fieldOptions, useFieldName } from './rules';

const NOTE_MAX = 5000;

/**
 * Actions that run after a change is committed (REQ-RUL-010, REQ-WF-003 "after"), in order:
 * set a field, or add a private note. Notifications, tasks and webhooks join with their WPs.
 */
export function AfterActions({
  fields,
  actions,
  onChange,
  testId,
}: {
  fields: RuleFieldOut[];
  actions: TriggerActionIO[];
  onChange: (next: TriggerActionIO[]) => void;
  testId: string;
}) {
  const t = useLabel();
  const name = useFieldName();
  const settable = fields.filter((f) => f.settable);
  const byName = new Map(settable.map((f) => [f.name, f]));
  const update = (index: number, next: TriggerActionIO) => {
    onChange(actions.map((a, i) => (i === index ? next : a)));
  };
  return (
    <Space direction="vertical" style={{ width: '100%' }} data-testid={testId}>
      {actions.map((action, index) => {
        const field = action.field != null ? byName.get(action.field) : undefined;
        const id = `${testId}-${String(index)}`;
        return (
          // Actions have no ID: they are edited in place.
          <Flex key={index} gap={8} wrap align="center" data-testid={id}>
            <Select
              aria-label={t('automation.action_kind')}
              value={action.kind}
              onChange={(kind: TriggerActionIO['kind']) => {
                update(
                  index,
                  kind === 'set' ? emptyAction() : { kind, text: '', mode: 'fill_empty' },
                );
              }}
              options={(['set', 'note'] as const).map((k) => ({
                value: k,
                label: t(`trigger_action_kind.${k}`),
              }))}
              style={{ minWidth: 180 }}
              data-testid={`${id}-kind`}
            />
            {action.kind === 'set' ? (
              <>
                <Select
                  aria-label={t('automation.conditions.field')}
                  showSearch
                  optionFilterProp="label"
                  value={action.field ?? undefined}
                  placeholder={t('automation.conditions.field')}
                  onChange={(next: string) => {
                    update(index, { ...action, field: next, value: null });
                  }}
                  options={fieldOptions(settable, name)}
                  style={{ minWidth: 200 }}
                  data-testid={`${id}-field`}
                />
                {field !== undefined && (
                  <ValueInput
                    field={field}
                    value={action.value}
                    onChange={(value) => {
                      update(index, { ...action, value });
                    }}
                    testId={`${id}-value`}
                    ariaLabel={t('automation.conditions.value')}
                  />
                )}
                <Select
                  aria-label={t('automation.action_mode')}
                  value={action.mode}
                  onChange={(mode: TriggerActionIO['mode']) => {
                    update(index, { ...action, mode });
                  }}
                  options={(['fill_empty', 'overwrite'] as const).map((m) => ({
                    value: m,
                    label: t(`rule_action_mode.${m}`),
                  }))}
                  style={{ minWidth: 200 }}
                  data-testid={`${id}-mode`}
                />
              </>
            ) : (
              <Input.TextArea
                rows={2}
                style={{ flex: 1, minWidth: 260 }}
                value={action.text ?? ''}
                onChange={(event) => {
                  update(index, { ...action, text: event.target.value });
                }}
                count={lengthLimit(NOTE_MAX)}
                aria-label={t('automation.note_text')}
                data-testid={`${id}-text`}
              />
            )}
            <Button
              aria-label={t('automation.action_remove')}
              onClick={() => {
                onChange(actions.filter((_, i) => i !== index));
              }}
            >
              {t('automation.remove')}
            </Button>
          </Flex>
        );
      })}
      <Button
        icon={<PlusOutlined />}
        onClick={() => {
          onChange([...actions, emptyAction()]);
        }}
        data-testid={`${testId}-add`}
      >
        {t('automation.action_add')}
      </Button>
    </Space>
  );
}
