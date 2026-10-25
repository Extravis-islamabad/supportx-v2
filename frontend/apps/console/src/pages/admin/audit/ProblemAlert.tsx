import { Alert } from 'antd';

import { CopyReference, describeError, useLabel } from '@supportx/ui';

/** A failed request in plain words, with the support reference (never a code). */
export function ProblemAlert({ error }: { error: unknown }) {
  const t = useLabel();
  const described = describeError(error, t);
  return (
    <Alert
      type="error"
      showIcon
      style={{ marginTop: 12 }}
      message={described.title}
      description={
        <>
          {described.detail}
          {described.reference !== null && <CopyReference reference={described.reference} />}
        </>
      }
      data-testid="audit-problem"
    />
  );
}
