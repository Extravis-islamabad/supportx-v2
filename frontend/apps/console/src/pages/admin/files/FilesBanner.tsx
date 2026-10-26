import { Alert } from 'antd';
import { Link } from 'react-router';

import { useFileStatus } from '@supportx/api-client';
import { useAccess, useLabel } from '@supportx/ui';

/**
 * File scanning that needs an administrator (D-082 D3, never silent): no scanner installed, the
 * scanner not answering, signatures older than 7 days, files that could not be checked or were
 * stored unscanned. Shown to holders of `files.manage` until the cause is gone.
 */
export function FilesBanner({ showLink = true }: { showLink?: boolean }) {
  const t = useLabel();
  const { can } = useAccess();
  const allowed = can('files.manage');
  const status = useFileStatus(allowed);
  const warnings = status.data?.warnings ?? [];
  if (!allowed || warnings.length === 0) return null;
  return (
    <Alert
      type="warning"
      showIcon
      role="alert"
      data-testid="files-banner"
      message={t('files.banner.title')}
      description={
        <>
          {warnings.map((warning) => t(`file_warning.${warning}`)).join(' ')}{' '}
          {/* Underlined: a link inside text must not rely on colour alone (WCAG 1.4.1, axe). */}
          {showLink && (
            <Link to="/admin/files" style={{ textDecoration: 'underline' }}>
              {t('files.banner.open')}
            </Link>
          )}
        </>
      }
    />
  );
}
