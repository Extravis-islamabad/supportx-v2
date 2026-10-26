import { Button, Flex, Modal, Spin, Typography } from 'antd';
import { useEffect, useState } from 'react';

import { fileLink, type StoredFile } from '@supportx/api-client';

import { useLabel } from '../appearance';
import { reportError } from '../errors';

export interface FilePreviewProps {
  file: StoredFile | null;
  onClose: () => void;
}

/**
 * Preview an image or a PDF without downloading it (REQ-INC-079 AC4). The link is fresh, lives
 * minutes and is checked against the user's access on the server; it is never stored. Images use
 * the browser's own viewer inside the dialog, PDFs its PDF viewer in a frame.
 */
export function FilePreview({ file, onClose }: FilePreviewProps) {
  const t = useLabel();
  // The link of the file being shown (a link for another file is never shown).
  const [link, setLink] = useState<{ id: string; url: string } | null>(null);
  const url = file !== null && link?.id === file.id ? link.url : null;
  useEffect(() => {
    if (file === null) return;
    let live = true;
    fileLink(file.id, 'inline')
      .then((found) => {
        if (live) setLink({ id: file.id, url: found });
      })
      .catch((error: unknown) => {
        reportError(error);
        onClose();
      });
    return () => {
      live = false;
    };
  }, [file, onClose]);

  return (
    <Modal
      open={file !== null}
      onCancel={onClose}
      title={file?.name}
      width={file?.kind === 'pdf' ? 960 : 760}
      footer={<Button onClick={onClose}>{t('files.close')}</Button>}
      data-testid="file-preview"
      destroyOnHidden
    >
      {url === null ? (
        <Flex justify="center" style={{ padding: 48 }}>
          <Spin aria-label={t('shell.loading')} />
        </Flex>
      ) : file?.kind === 'pdf' ? (
        <iframe
          src={url}
          title={file.name}
          style={{ width: '100%', height: '70vh', border: 0 }}
          data-testid="file-preview-pdf"
        />
      ) : (
        <Flex vertical align="center" gap={8}>
          <img
            src={url}
            alt={file?.name ?? ''}
            style={{ maxWidth: '100%', maxHeight: '70vh', objectFit: 'contain' }}
            data-testid="file-preview-image"
          />
          <Typography.Text type="secondary">{t('files.preview_hint')}</Typography.Text>
        </Flex>
      )}
    </Modal>
  );
}
