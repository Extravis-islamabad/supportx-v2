import { Alert } from 'antd';
import { useState } from 'react';

import { useLabel } from '../appearance';
import { useLicence } from './context';

const DISMISS_KEY = 'supportx.grace_banner_dismissed';

function dismissedFor(): string | null {
  try {
    return window.sessionStorage.getItem(DISMISS_KEY);
  } catch {
    return null;
  }
}

/**
 * Licence notices (architecture.md §13.6):
 * - read-only: for everyone, cannot be dismissed, explains that viewing and export still work;
 * - grace: for tenant admins only, dismissible for this browser session, with the days left.
 */
export function LicenceBanners() {
  const t = useLabel();
  const { entitlements, isAdmin } = useLicence();
  const [dismissed, setDismissed] = useState(dismissedFor);

  if (entitlements === null) return null;
  if (!entitlements.writable) {
    const reason = entitlements.state_reason ?? 'no_entitlement';
    return (
      <Alert
        data-testid="read-only-banner"
        type="error"
        banner
        showIcon
        message={t('licence.read_only_banner')}
        description={t(`entitlement_reason.${reason}`)}
      />
    );
  }
  // Keyed by days left: dismissing today's warning does not hide tomorrow's.
  const days = entitlements.days_left;
  const key = `${entitlements.state}:${String(days)}`;
  if (
    entitlements.state === 'grace' &&
    entitlements.admin_warning &&
    isAdmin &&
    dismissed !== key
  ) {
    return (
      <Alert
        data-testid="grace-banner"
        type="warning"
        banner
        showIcon
        closable
        message={t('licence.grace_banner', { count: days ?? 0 })}
        description={t('licence.grace_warning')}
        onClose={() => {
          setDismissed(key);
          try {
            window.sessionStorage.setItem(DISMISS_KEY, key);
          } catch {
            // dismissed for this page view only
          }
        }}
      />
    );
  }
  return null;
}
