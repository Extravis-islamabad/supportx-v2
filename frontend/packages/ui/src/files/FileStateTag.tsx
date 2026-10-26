import {
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  LoadingOutlined,
  StopOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { Tag, theme } from 'antd';
import type { ReactNode } from 'react';

import type { FileState } from '@supportx/api-client';

import { useLabel } from '../appearance';

/**
 * A file's scan state in words, with an icon and a coloured mark on a neutral tag (colour alone
 * never carries the meaning, and the text keeps its contrast in every theme). The state is
 * announced politely when it changes ("Checking for malware" → "Ready").
 */
export function FileStateTag({ state }: { state: FileState }) {
  const t = useLabel();
  const { token } = theme.useToken();
  const looks: Record<FileState, { icon: ReactNode; color: string }> = {
    scanning: { icon: <LoadingOutlined />, color: token.colorInfo },
    clean: { icon: <CheckCircleOutlined />, color: token.colorSuccess },
    infected: { icon: <StopOutlined />, color: token.colorError },
    scan_failed: { icon: <ExclamationCircleOutlined />, color: token.colorWarning },
    not_scanned: { icon: <WarningOutlined />, color: token.colorWarning },
    deleted: { icon: <StopOutlined />, color: token.colorTextTertiary },
  };
  const look = looks[state];
  return (
    <Tag
      icon={<span style={{ color: look.color, marginInlineEnd: 4 }}>{look.icon}</span>}
      data-testid={`file-state-${state}`}
      role="status"
      aria-live="polite"
    >
      {t(`file_state.${state}`)}
    </Tag>
  );
}
