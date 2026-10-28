import { Alert } from 'antd';

import { useLabel } from '@supportx/ui';

import type { EditorProblem } from './problems';

/** The list above the editor: each problem names its field, which is marked too. */
export function ProblemList({
  problems,
  testId,
}: {
  problems: readonly EditorProblem[];
  testId: string;
}) {
  const t = useLabel();
  if (problems.length === 0) return null;
  return (
    <Alert
      type="error"
      showIcon
      data-testid={testId}
      message={t('automation.problems')}
      description={
        <ul style={{ margin: 0 }}>
          {problems.map((p, index) => (
            // Problems have no ID; the server's order is stable for one answer.
            <li key={index} data-path={p.path}>
              {p.where === ''
                ? p.message
                : t('automation.problem.at', { where: p.where, message: p.message })}
            </li>
          ))}
        </ul>
      }
    />
  );
}
