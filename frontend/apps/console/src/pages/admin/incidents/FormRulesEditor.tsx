import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { Button, Card, Checkbox, Flex, Input, Select, Space, Typography } from 'antd';

import {
  FilterBuilder,
  fromDsl,
  toDsl,
  type FilterFieldOption,
  type FilterModel,
  type FormRule,
  type RuleAction,
  type RuleActionKind,
  type RuleCondition,
} from '@supportx/forms';
import { useLabel } from '@supportx/ui';

// The form rule editor (WP-046a S5b; REQ-INC-037): "when these conditions hold, do these
// things". The condition is the shared filter builder over the form's choice fields (their
// operators are exactly what the rule evaluator knows), so a rule reads like a list filter; the
// browser applies the rules as the form is filled and the server enforces them on every save.

const ACTIONS: readonly RuleActionKind[] = ['show', 'hide', 'require', 'lock', 'set'];
const newId = (): string => `r_${Math.random().toString(36).slice(2, 10)}`;

function move<T>(list: readonly T[], from: number, to: number): T[] {
  const next = [...list];
  const [item] = next.splice(from, 1);
  if (item !== undefined) next.splice(to, 0, item);
  return next;
}

export function FormRulesEditor({
  value,
  onChange,
  conditionFields,
  fields,
  fixed,
  fieldLabel,
}: {
  value: FormRule[];
  onChange: (next: FormRule[]) => void;
  /** Fields a condition may test: the form's choice fields, with their choices. */
  conditionFields: FilterFieldOption[];
  /** Every field an action may change. */
  fields: readonly string[];
  /** Always shown and required: never hidden or locked. */
  fixed: ReadonlySet<string>;
  fieldLabel: (name: string) => string;
}) {
  const t = useLabel();
  const choicesOf = new Map(conditionFields.map((f) => [f.name, f.choices]));
  const setRule = (index: number, rule: FormRule) => {
    onChange(value.map((r, i) => (i === index ? rule : r)));
  };
  const setAction = (index: number, at: number, action: RuleAction) => {
    const rule = value[index];
    if (rule !== undefined)
      setRule(index, { ...rule, then: rule.then.map((a, i) => (i === at ? action : a)) });
  };
  const firstField = conditionFields[0];

  return (
    <Space direction="vertical" style={{ width: '100%' }} data-testid="tpl-frules">
      <Typography.Title level={3} style={{ marginTop: 24 }}>
        {t('templates.form_rules')}
      </Typography.Title>
      <Typography.Paragraph type="secondary">{t('templates.form_rules_help')}</Typography.Paragraph>
      {value.map((rule, index) => {
        const title = t('templates.rule_title', { n: index + 1 });
        const model: FilterModel = fromDsl(rule.when) ?? { join: 'and', rows: [] };
        return (
          <Card
            key={rule.id}
            size="small"
            title={title}
            data-testid={`tpl-frule-${String(index)}`}
            extra={
              <Space size={4}>
                <Button
                  size="small"
                  icon={<ArrowUpOutlined />}
                  disabled={index === 0}
                  aria-label={t('templates.rule_up', { name: title })}
                  onClick={() => {
                    onChange(move(value, index, index - 1));
                  }}
                />
                <Button
                  size="small"
                  icon={<ArrowDownOutlined />}
                  disabled={index === value.length - 1}
                  aria-label={t('templates.rule_down', { name: title })}
                  onClick={() => {
                    onChange(move(value, index, index + 1));
                  }}
                />
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  aria-label={t('templates.rule_remove', { name: title })}
                  onClick={() => {
                    onChange(value.filter((_, i) => i !== index));
                  }}
                  data-testid={`tpl-frule-${String(index)}-remove`}
                />
              </Space>
            }
          >
            <Typography.Text strong>{t('templates.rule_when')}</Typography.Text>
            <FilterBuilder
              fields={conditionFields}
              value={model}
              onChange={(next) => {
                setRule(index, { ...rule, when: (toDsl(next) ?? { and: [] }) as RuleCondition });
              }}
              testId={`tpl-frule-${String(index)}-when`}
            />
            <Typography.Text strong style={{ display: 'block', marginTop: 12 }}>
              {t('templates.rule_then')}
            </Typography.Text>
            {rule.then.map((action, at) => {
              const choices = choicesOf.get(action.field);
              const fieldOptions = fields
                .filter((f) => !(fixed.has(f) && (action.do === 'hide' || action.do === 'lock')))
                .map((f) => ({ value: f, label: fieldLabel(f) }));
              return (
                <Flex
                  key={at}
                  gap={8}
                  wrap
                  align="center"
                  style={{ marginTop: 8 }}
                  data-testid={`tpl-frule-${String(index)}-then-${String(at)}`}
                >
                  <Select<RuleActionKind>
                    style={{ minWidth: 140 }}
                    aria-label={t('templates.rule_do')}
                    value={action.do}
                    onChange={(next) => {
                      setAction(index, at, { do: next, field: action.field });
                    }}
                    options={ACTIONS.map((a) => ({ value: a, label: t(`form_rule_action.${a}`) }))}
                    data-testid={`tpl-frule-${String(index)}-do-${String(at)}`}
                  />
                  <Select<string>
                    style={{ minWidth: 200 }}
                    aria-label={t('templates.rule_field')}
                    value={action.field}
                    showSearch
                    optionFilterProp="label"
                    onChange={(next) => {
                      setAction(index, at, { do: action.do, field: next });
                    }}
                    options={fieldOptions}
                    data-testid={`tpl-frule-${String(index)}-field-${String(at)}`}
                  />
                  {action.do === 'set' &&
                    (choices !== undefined ? (
                      <Select<string>
                        style={{ minWidth: 160 }}
                        aria-label={t('templates.rule_value')}
                        value={typeof action.value === 'string' ? action.value : undefined}
                        onChange={(next) => {
                          setAction(index, at, { ...action, value: next });
                        }}
                        options={choices}
                      />
                    ) : (
                      <Input
                        style={{ width: 200 }}
                        dir="auto"
                        aria-label={t('templates.rule_value')}
                        value={typeof action.value === 'string' ? action.value : ''}
                        onChange={(event) => {
                          setAction(index, at, { ...action, value: event.target.value });
                        }}
                      />
                    ))}
                  {action.do === 'hide' && (
                    <Checkbox
                      checked={action.keep_value === true}
                      onChange={(event) => {
                        setAction(index, at, { ...action, keep_value: event.target.checked });
                      }}
                    >
                      {t('templates.rule_keep_value')}
                    </Checkbox>
                  )}
                  <Button
                    size="small"
                    icon={<DeleteOutlined />}
                    disabled={rule.then.length === 1}
                    aria-label={t('templates.rule_action_remove')}
                    onClick={() => {
                      setRule(index, { ...rule, then: rule.then.filter((_, i) => i !== at) });
                    }}
                  />
                </Flex>
              );
            })}
            <Button
              size="small"
              icon={<PlusOutlined />}
              style={{ marginTop: 8 }}
              disabled={rule.then.length >= 20}
              onClick={() => {
                setRule(index, {
                  ...rule,
                  then: [...rule.then, { do: 'require', field: fields[0] ?? 'subject' }],
                });
              }}
              data-testid={`tpl-frule-${String(index)}-then-add`}
            >
              {t('templates.rule_action_add')}
            </Button>
          </Card>
        );
      })}
      <Button
        icon={<PlusOutlined />}
        disabled={value.length >= 50 || firstField === undefined}
        onClick={() => {
          if (firstField === undefined) return;
          onChange([
            ...value,
            {
              id: newId(),
              when: { field: firstField.name, op: 'is_not_null' },
              then: [{ do: 'require', field: fields.find((f) => !fixed.has(f)) ?? 'subject' }],
            },
          ]);
        }}
        data-testid="tpl-frule-add"
      >
        {t('templates.rule_add')}
      </Button>
    </Space>
  );
}
