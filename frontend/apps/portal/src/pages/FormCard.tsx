import { Card } from 'antd';
import type { ReactNode } from 'react';

/** A portal form on a white card, as the console's forms are (QA6-PRT-02). */
export function FormCard({ children, testId }: { children: ReactNode; testId: string }) {
  return (
    <Card data-testid={testId} styles={{ body: { padding: 24 } }}>
      {children}
    </Card>
  );
}
