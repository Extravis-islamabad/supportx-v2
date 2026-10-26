import { LoadingOutlined, StopOutlined, WarningOutlined } from '@ant-design/icons';
import { NodeViewWrapper, type ReactNodeViewProps } from '@tiptap/react';
import { Typography } from 'antd';
import type { ReactNode } from 'react';

import { fileImageUrl, useFile } from '@supportx/api-client';

import { useLabel } from '../appearance';

const CHECKING_POLL_MS = 2000;

function Placeholder({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <Typography.Text type="secondary" role="status">
      {icon} {text}
    </Typography.Text>
  );
}

/** How an inline image looks while it uploads, is checked, is blocked, or is ready. */
export function InlineImageView({ node, selected }: ReactNodeViewProps) {
  const t = useLabel();
  const fileId = typeof node.attrs.fileId === 'string' ? node.attrs.fileId : undefined;
  const failed = typeof node.attrs.failed === 'string' ? node.attrs.failed : null;
  const file = useFile(fileId, (query) =>
    query.state.data?.state === 'scanning' ? CHECKING_POLL_MS : false,
  );
  const state = file.data?.state;
  let body: ReactNode;
  if (failed !== null) {
    body = <Placeholder icon={<WarningOutlined />} text={failed} />;
  } else if (fileId === undefined) {
    body = <Placeholder icon={<LoadingOutlined />} text={t('richtext.image_uploading')} />;
  } else if (state === 'infected' || state === 'deleted') {
    body = <Placeholder icon={<StopOutlined />} text={t('richtext.image_blocked')} />;
  } else if (file.data?.openable === true) {
    body = (
      <img
        src={fileImageUrl(fileId, 'inline')}
        alt={typeof node.attrs.alt === 'string' ? node.attrs.alt : ''}
        style={{ maxWidth: '100%', height: 'auto' }}
      />
    );
  } else {
    body = <Placeholder icon={<LoadingOutlined />} text={t('richtext.image_checking')} />;
  }
  return (
    <NodeViewWrapper
      className={`sx-inline-image${selected ? ' sx-inline-image-selected' : ''}`}
      data-file-id={fileId}
    >
      {body}
    </NodeViewWrapper>
  );
}
