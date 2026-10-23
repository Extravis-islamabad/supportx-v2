import { Alert, Flex, Typography } from 'antd';

import { useSession } from '@supportx/api-client';
import { useAppearance, useLabel, useLicence, useLiveAnnouncementFeed } from '@supportx/ui';

const ALERT_TYPE = { info: 'info', warning: 'warning', critical: 'error' } as const;

/**
 * Portal landing page: a greeting and the announcements live for this user, kept current with
 * no reload (WP-012). The AI-assistant landing, catalogue and requests arrive with WP-015.
 */
export function HomePage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const session = useSession().data;
  const licence = useLicence();
  const feed = useLiveAnnouncementFeed(licence.has('incident'));
  const items = feed.data?.items ?? [];
  const format = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });
  return (
    <>
      <Typography.Title level={1}>
        {t('home.title', { name: session?.user.display_name ?? '' })}
      </Typography.Title>
      <Typography.Paragraph type="secondary">{t('app.portal.name')}</Typography.Paragraph>
      <section aria-labelledby="announcements-heading" data-testid="portal-announcements">
        <Typography.Title level={2} id="announcements-heading">
          {t('announcements.title')}
        </Typography.Title>
        {items.length === 0 ? (
          <Typography.Paragraph type="secondary" data-testid="portal-announcements-empty">
            {t('announcements.none_live')}
          </Typography.Paragraph>
        ) : (
          <Flex vertical gap={12}>
            {items.map((item) => (
              <Alert
                key={item.id}
                type={ALERT_TYPE[item.severity]}
                showIcon
                data-testid={`portal-announcement-${item.id}`}
                message={
                  <Typography.Text strong>
                    {t(`announcement_severity.${item.severity}`)}: {item.title}
                  </Typography.Text>
                }
                description={
                  <>
                    <Typography.Paragraph style={{ whiteSpace: 'pre-line', marginBottom: 4 }}>
                      {item.body}
                    </Typography.Paragraph>
                    {item.published_at !== null && (
                      <Typography.Text type="secondary">
                        {t('announcements.published_on', {
                          time: format.format(new Date(item.published_at)),
                        })}
                      </Typography.Text>
                    )}
                  </>
                }
              />
            ))}
          </Flex>
        )}
      </section>
    </>
  );
}
