import { Result } from 'antd';
import { useEffect } from 'react';

import { useLabel } from '@supportx/ui';

import { TEST_DONE_MESSAGE } from './SsoCard';

/**
 * Where the single sign-on test's pop-up lands (WP-039): it tells the admin's screen that the
 * test is done, then closes. Opened by hand (pop-up blocked), it just says so.
 */
export function SsoTestDonePage() {
  const t = useLabel();
  useEffect(() => {
    const opener = window.opener as Window | null;
    if (opener !== null) {
      opener.postMessage(TEST_DONE_MESSAGE, window.location.origin);
      window.close();
    }
  }, []);
  return (
    <Result status="success" title={t('security.sso.test_done')} data-testid="sso-test-done" />
  );
}
