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
  /** The tab or part the field is on, already translated ("Fulfilment"): read before the label. */
  section?: string;
}

/**
 * The one error pattern of long settings forms (QA6S-SHELL-07): every field shows its own error
 * under it, and this summary lists the fields by label as links that move focus there. Focus goes
 * to the first invalid field when the summary appears. Short forms need only the inline errors.
 */
export function FormErrorSummary({
  problems,
  onSelect,
}: {
  problems: FieldProblem[];
  /** Called before focus moves to a field: show its tab first (lane B: tabbed drawers). */
  onSelect?: (fieldId: string) => void;
}) {
  const t = useLabel();
  const first = problems[0]?.fieldId;
  const shown = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (first === undefined || shown.current === first) return;
    shown.current = first;
    onSelect?.(first);
    // After the caller's tab switch has rendered.
    window.setTimeout(() => document.getElementById(first)?.focus(), 0);
  }, [first, onSelect]);
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
                onSelect?.(p.fieldId);
                window.setTimeout(() => document.getElementById(p.fieldId)?.focus(), 0);
              }}
            >
              {`${p.section === undefined ? '' : `${p.section} › `}${p.label}: ${p.message}`}
            </Button>
          ))}
        </Flex>
      }
    />
  );
}
