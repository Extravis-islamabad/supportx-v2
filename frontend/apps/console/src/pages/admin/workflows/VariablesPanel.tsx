import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Flex, Input, Select, Typography } from 'antd';

import { VARIABLE_KINDS, type VariableKind, type WorkflowVariable } from '@supportx/flow';
import { EmptyText, lengthLimit, useLabel } from '@supportx/ui';

// The server's limits (domain/workflows.py): MAX_VARIABLES, ID_MAX, and a name of letters,
// digits, "_" and "-".
const MAX_VARIABLES = 50;
const NAME_MAX = 40;
const NAME = /^[A-Za-z0-9_-]+$/;

/** Why a variable's name cannot be saved, as a label key, or undefined. */
function nameProblem(name: string, others: readonly WorkflowVariable[]): string | undefined {
  if (name === '') return 'workflows.variables.name_required';
  if (!NAME.test(name)) return 'workflows.variables.name_invalid';
  if (others.some((v) => v.name === name)) return 'workflows.variables.name_taken';
  return undefined;
}

/**
 * The workflow's own variables (QA F-05: no JSON): a name and what it holds. Set variable,
 * webhook and function steps fill them; conditions read them like the record's fields.
 */
export function VariablesPanel({
  variables,
  readOnly,
  onChange,
}: {
  variables: WorkflowVariable[];
  readOnly: boolean;
  onChange: (next: WorkflowVariable[]) => void;
}) {
  const t = useLabel();
  const set = (i: number, patch: Partial<WorkflowVariable>) => {
    onChange(variables.map((v, j) => (j === i ? { ...v, ...patch } : v)));
  };
  return (
    <Flex vertical gap={8} data-testid="designer-variables">
      <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
        {t('workflows.variables.help')}
      </Typography.Paragraph>
      {variables.length === 0 && <EmptyText>{t('workflows.variables.none')}</EmptyText>}
      {variables.map((v, i) => {
        const problem = nameProblem(
          v.name,
          variables.filter((_, j) => j !== i),
        );
        const n = i + 1;
        return (
          <Flex key={i} gap={8} align="start" wrap data-testid={`variable-${String(n)}`}>
            <Flex vertical style={{ flex: '1 1 140px', minWidth: 0 }}>
              <Input
                value={v.name}
                disabled={readOnly}
                status={problem === undefined ? undefined : 'error'}
                aria-label={t('workflows.variables.name', { n })}
                placeholder={t('workflows.variables.name_placeholder')}
                count={lengthLimit(NAME_MAX)}
                onChange={(e) => {
                  set(i, { name: e.target.value.trim() });
                }}
                data-testid={`variable-${String(n)}-name`}
              />
              {problem !== undefined && (
                <Typography.Text type="danger" style={{ fontSize: 12 }}>
                  {t(problem)}
                </Typography.Text>
              )}
            </Flex>
            <Select<VariableKind>
              value={v.kind}
              disabled={readOnly}
              aria-label={t('workflows.variables.kind', { n })}
              style={{ flex: '0 1 140px', minWidth: 120 }}
              onChange={(kind) => {
                set(i, { kind });
              }}
              options={VARIABLE_KINDS.map((k) => ({ value: k, label: t(`rule_field_kind.${k}`) }))}
              data-testid={`variable-${String(n)}-kind`}
            />
            <Button
              type="text"
              icon={<DeleteOutlined />}
              disabled={readOnly}
              aria-label={t('workflows.variables.remove', { n })}
              onClick={() => {
                onChange(variables.filter((_, j) => j !== i));
              }}
              data-testid={`variable-${String(n)}-remove`}
            />
          </Flex>
        );
      })}
      <div>
        <Button
          icon={<PlusOutlined />}
          disabled={readOnly || variables.length >= MAX_VARIABLES}
          onClick={() => {
            onChange([...variables, { name: '', kind: 'text' }]);
          }}
          data-testid="variable-add"
        >
          {t('workflows.variables.add')}
        </Button>
      </div>
    </Flex>
  );
}
