import { Alert } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';

import { queryKeys, useAuditStatus } from '@supportx/api-client';
import { refreshList, useListChannel } from '@supportx/realtime';
import { useAccess, useLabel } from '@supportx/ui';

/**
 * The audit alert banner (REQ-AUD-010, D-075 item 8): shown to holders of `audit.view` while the
 * chain has an unresolved problem (a failed verification, entries waiting too long to be
 * sealed). It stays until a later full verification passes. Live through the audit channel.
 */
export function AuditAlertBanner({ showLink = true }: { showLink?: boolean }) {
  const t = useLabel();
  const { can } = useAccess();
  const allowed = can('audit.view');
  const status = useAuditStatus(allowed);
  const queryClient = useQueryClient();
  useListChannel(allowed ? 'audit' : null, () => {
    refreshList(queryClient, queryKeys.audit.status);
  });
  const alert = status.data?.alert;
  if (!allowed || alert === null || alert === undefined) return null;
  return (
    <Alert
      type="error"
      showIcon
      role="alert"
      data-testid="audit-alert-banner"
      message={t('audit.ui.banner.title')}
      description={
        <>
          {t(`audit.problem.${alert}`)}{' '}
          {showLink && <Link to="/admin/audit?tab=integrity">{t('audit.ui.banner.open')}</Link>}
        </>
      }
    />
  );
}
