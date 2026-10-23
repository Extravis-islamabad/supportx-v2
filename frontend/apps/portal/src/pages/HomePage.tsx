import { Typography } from 'antd';

import { useSession } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

/** Portal landing page. The AI-assistant landing, catalogue and requests arrive with WP-015. */
export function HomePage() {
  const t = useLabel();
  const session = useSession().data;
  return (
    <>
      <Typography.Title level={1}>
        {t('home.title', { name: session?.user.display_name ?? '' })}
      </Typography.Title>
      <Typography.Paragraph type="secondary">{t('app.portal.name')}</Typography.Paragraph>
    </>
  );
}
