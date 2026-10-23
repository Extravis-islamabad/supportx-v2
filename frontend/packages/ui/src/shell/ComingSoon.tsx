import { Result } from 'antd';

import type { LabelKey } from '@supportx/labels';

import { useLabel } from '../appearance';

/** Placeholder for a section whose module has not been built yet. */
export function ComingSoon({ titleKey }: { titleKey: LabelKey }) {
  const t = useLabel();
  return (
    <Result
      status="info"
      title={<h1 style={{ fontSize: 'inherit', margin: 0 }}>{t(titleKey)}</h1>}
      subTitle={t('shell.coming_soon')}
    />
  );
}

/** A section the tenant's plan does not include (the server would answer 403 too). */
export function NotInPlan({ titleKey, isAdmin }: { titleKey: LabelKey; isAdmin: boolean }) {
  const t = useLabel();
  return (
    <Result
      status="403"
      title={<h1 style={{ fontSize: 'inherit', margin: 0 }}>{t(titleKey)}</h1>}
      subTitle={`${t('errors.entitlement_required')} ${isAdmin ? t('licence.upgrade_hint') : t('licence.ask_admin')}`}
    />
  );
}
