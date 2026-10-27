import { Alert, Flex, Typography } from 'antd';

import { useSession } from '@supportx/api-client';
import {
  brandText,
  useAppearance,
  useLabel,
  useLicence,
  useLiveAnnouncementFeed,
} from '@supportx/ui';

const ALERT_TYPE = { info: 'info', warning: 'warning', critical: 'error' } as const;

/**
 * Portal landing page: a greeting and the announcements live for this user, kept current with
 * no reload (WP-012). The AI-assistant landing, catalogue and requests arrive with WP-015.
 */
export function HomePage() {
  const t = useLabel();
  const { locale, mode, branding } = useAppearance();
  const session = useSession().data;
  const licence = useLicence();
  const feed = useLiveAnnouncementFeed(licence.has('incident'));
  const items = feed.data?.items ?? [];
  const format = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });
  return (
    <>
      {/* Welcome band in the brand gradient; white text on it reaches 4.97:1 at its lightest
          (branding.md). High contrast shows plain black on white instead. */}
      <section
        data-testid="portal-welcome"
        style={{
          borderRadius: 12,
          padding: '28px 32px',
          marginBottom: 32,
          ...(mode === 'high_contrast'
            ? { border: '2px solid #000000' }
            : {
                backgroundImage: `linear-gradient(90deg, ${branding.gradient[0]}, ${branding.gradient[1]})`,
                color: '#ffffff',
              }),
        }}
      >
        <Typography.Title level={1} style={{ color: 'inherit', marginTop: 0 }}>
          {t('home.title', { name: session?.user.display_name ?? '' })}
        </Typography.Title>
        {/* The tenant's welcome text, else its portal name, else ours (WP-017, REQ-PRT-016). */}
        <Typography.Paragraph
          style={{ color: 'inherit', marginBottom: 0, fontSize: 16, whiteSpace: 'pre-line' }}
        >
          {brandText(branding, 'welcomeText', locale) ??
            brandText(branding, 'portalName', locale) ??
            t('app.portal.name')}
        </Typography.Paragraph>
      </section>
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
