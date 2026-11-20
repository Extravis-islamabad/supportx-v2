import { Alert } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

import { queryKeys, useSession } from '@supportx/api-client';
import { usePersonalChannel } from '@supportx/realtime';
import { useDateTime, useLabel } from '@supportx/ui';

import { setHiddenPersonLabel } from './maskedPeople';

// The support account's own channel says its grant changed (WP-057 S4c-3): IDs only.
const GRANT_CHANGED = 'identity_access.support_grant_changed';

/**
 * Every page of a vendor support session says so (WP-057 S4c-3, D-178): who you are here and
 * when access ends. It can't be dismissed. The grant's end or extension reaches it live; at the
 * end the session is asked again, the server answers "signed out", and the whole console (its
 * requests and realtime) is replaced by the signed-out page (lane B (6)).
 */
export function SupportBanner() {
  const t = useLabel();
  const { format } = useDateTime();
  const queryClient = useQueryClient();
  const support = useSession().data?.support ?? null;
  const recheck = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.session });
  };
  usePersonalChannel((message) => {
    if (message.type === GRANT_CHANGED) recheck();
  });
  const endsAt = support?.ends_at;
  useEffect(() => {
    if (endsAt === undefined) return undefined;
    // A second after the end: the grant's own end, without waiting for any event.
    const wait = Math.max(Date.parse(endsAt) - Date.now() + 1000, 0);
    const timer = window.setTimeout(recheck, Math.min(wait, 2 ** 31 - 1));
    return () => {
      window.clearTimeout(timer);
    };
    // recheck is stable enough: it only invalidates the session query.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endsAt]);
  const masked = support?.contacts_masked === true;
  const hidden = t('vendor_support.person_hidden');
  useEffect(() => {
    setHiddenPersonLabel(masked ? hidden : null);
    return () => {
      setHiddenPersonLabel(null);
    };
  }, [masked, hidden]);
  if (support === null) return null;
  return (
    <Alert
      type="warning"
      showIcon
      banner
      role="status"
      data-testid="support-banner"
      message={t('vendor_support.banner.text', { time: format(support.ends_at) })}
      description={support.contacts_masked ? t('vendor_support.banner.masked') : undefined}
    />
  );
}
