import { useQuery } from '@tanstack/react-query';
import { Button, Flex, Modal, Typography } from 'antd';

import { api, call, queryKeys } from '@supportx/api-client';
import type { LabelKey } from '@supportx/labels';

import { useLabel } from '../appearance';
import { BrandLogo } from '../brand';

export interface AboutDialogProps {
  open: boolean;
  onClose: () => void;
  /** Labels key of the app's name, e.g. `app.console.name`. */
  appName: LabelKey;
}

/** About and version: the logo, the app, the server version (from GET /api/v1/health). */
export function AboutDialog({ open, onClose, appName }: AboutDialogProps) {
  const t = useLabel();
  const version = useQuery({
    queryKey: queryKeys.version,
    queryFn: async () => (await call(api.GET('/api/v1/health'))).version,
    // The dialog says so itself when the version cannot be read: no toast.
    meta: { silent: true },
    retry: false,
    staleTime: Infinity,
  });
  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={t('about.open')}
      footer={<Button onClick={onClose}>{t('about.close')}</Button>}
      data-testid="about-dialog"
    >
      <Flex vertical align="center" gap={12} style={{ paddingBlock: 16 }}>
        <BrandLogo height={48} />
        <Typography.Text strong>{t(appName)}</Typography.Text>
        <Typography.Text type="secondary" data-testid="about-version">
          {version.isSuccess
            ? t('about.version', { version: version.data })
            : version.isError
              ? t('about.version_unavailable')
              : t('shell.loading')}
        </Typography.Text>
        <Typography.Text type="secondary">{t('about.made_by')}</Typography.Text>
      </Flex>
    </Modal>
  );
}
