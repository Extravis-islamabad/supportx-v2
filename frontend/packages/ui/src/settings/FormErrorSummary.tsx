import { Alert, Button, Flex } from 'antd';
import { useEffect, useRef } from 'react';

import { useLabel } from '../appearance';

export interface FieldProblem {
  /** The input's id, to move focus there. */
  fieldId: string;
  /** The field's label, as the form shows it. */
  label: string;
  /** What is wrong, already translated. */
  message: string;
}

/**
 * The one error pattern of long settings forms (QA6S-SHELL-07): every field shows its own error
 * under it, and this summary lists the fields by label as links that move focus there. Focus goes
 * to the first invalid field when the summary appears. Short forms need only the inline errors.
 */
export function FormErrorSummary({ problems }: { problems: FieldProblem[] }) {
  const t = useLabel();
  const first = problems[0]?.fieldId;
  const shown = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (first === undefined || shown.current === first) return;
    shown.current = first;
    document.getElementById(first)?.focus();
  }, [first]);
  if (problems.length === 0) return null;
  return (
    <Alert
      type="error"
      showIcon
      role="alert"
      data-testid="form-error-summary"
      style={{ marginBottom: 16 }}
      message={t('settings.fix_fields', { count: problems.length })}
      description={
        <Flex vertical gap={2}>
          {problems.map((p) => (
            <Button
              key={p.fieldId}
              type="link"
              size="small"
              style={{ padding: 0, height: 'auto', textAlign: 'start' }}
              onClick={() => {
                document.getElementById(p.fieldId)?.focus();
              }}
            >
              {`${p.label}: ${p.message}`}
            </Button>
          ))}
        </Flex>
      }
    />
  );
}
