import { Result } from 'antd';

import { useLabel } from '@supportx/ui';

export const SSO_TEST_DONE_PATH = '/sso-test-done';

/**
 * Where a single sign-on test lands (WP-039), outside the session gate: the test runs in a
 * private window, signed in to SupportX as nobody. The admin's screen shows the result.
 */
export function SsoTestDonePage() {
  const t = useLabel();
  return (
    <div data-testid="sso-test-done">
      <Result status="success" title={t('security.sso.test_done')} />
    </div>
  );
}
