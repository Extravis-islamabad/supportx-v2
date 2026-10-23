import { Button, Result, Space } from 'antd';
import { Component, type ErrorInfo, type ReactNode } from 'react';

import { useLabel } from '../appearance';
import { CopyReference } from './CopyReference';

interface State {
  reference: string | null;
}

/**
 * Catches render crashes anywhere below it and shows a friendly page instead of a blank screen
 * or a stack trace. The reference ties the user's report to the console log entry.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  override state: State = { reference: null };

  static getDerivedStateFromError(): State {
    return { reference: crypto.randomUUID() };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[ui] crash', this.state.reference, error, info.componentStack);
  }

  override render() {
    if (this.state.reference !== null) return <CrashPage reference={this.state.reference} />;
    return this.props.children;
  }
}

export function CrashPage({ reference }: { reference: string | null }) {
  const t = useLabel();
  return (
    <Result
      status="error"
      title={t('crash.title')}
      subTitle={t('crash.body')}
      extra={
        <Space>
          <Button
            type="primary"
            onClick={() => {
              window.location.reload();
            }}
          >
            {t('crash.reload')}
          </Button>
          {reference !== null && <CopyReference reference={reference} />}
        </Space>
      }
    />
  );
}
