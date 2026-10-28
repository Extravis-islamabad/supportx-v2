import { Alert } from 'antd';

import { ApiError } from '@supportx/api-client';
import { CopyReference, describeError, useLabel } from '@supportx/ui';

/**
 * A failed request in plain words (never a code). An expected refusal (a rule, a validation) is
 * a warning without the support reference; only a real failure carries it (QA WP-029 BUG-02).
 */
export function ProblemAlert({ error }: { error: unknown }) {
  const t = useLabel();
  const described = describeError(error, t);
  const refusal = error instanceof ApiError && error.isRefusal;
  return (
    <Alert
      type={refusal ? 'warning' : 'error'}
      showIcon
      style={{ marginTop: 12 }}
      message={described.title}
      description={
        <>
          {described.detail}
          {!refusal && described.reference !== null && (
            <CopyReference reference={described.reference} />
          )}
        </>
      }
      data-testid="audit-problem"
    />
  );
}
