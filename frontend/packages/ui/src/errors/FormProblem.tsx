import { Alert } from 'antd';

import { useLabel } from '../appearance';
import { describeError } from './describe';
import type { FormProblemState } from './useFormProblem';

/** Why the form was not saved, in the user's language, where they are looking. */
export function FormProblem({ problem }: { problem: FormProblemState }) {
  const t = useLabel();
  if (problem.error === null) return null;
  const { title, detail } = describeError(problem.error, t);
  return (
    <Alert
      type="warning"
      showIcon
      role="alert"
      data-testid="form-problem"
      message={title}
      description={detail}
      closable
      onClose={problem.clear}
      style={{ marginBottom: 16 }}
    />
  );
}
