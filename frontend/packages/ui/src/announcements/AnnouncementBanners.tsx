import { Alert, Button, Flex, Typography } from 'antd';
import { useDismissAnnouncement } from '@supportx/api-client';

import { useAppearance, useLabel } from '../appearance';
import { clampLineHeight } from '../fonts/fonts';
import { useLiveAnnouncementFeed } from './useLiveAnnouncementFeed';

const ALERT_TYPE = { info: 'info', warning: 'warning', critical: 'error' } as const;
export interface AnnouncementBannersProps {
  /** Whether this tenant's plan includes announcements (no calls otherwise). */
  enabled?: boolean;
  /** Where "View" goes (console: the announcement page); without it there is no link. */
  onOpen?: (id: string) => void;
}

/** Banners for live announcements marked "show as banner", above every page of the app. */
export function AnnouncementBanners({ enabled = true, onOpen }: AnnouncementBannersProps) {
  const t = useLabel();
  const { urduScript } = useAppearance();
  const feed = useLiveAnnouncementFeed(enabled);
  const dismiss = useDismissAnnouncement();
  // Dismissed on every device (WP-032 D7, REQ-PRT-009 AC2): the person's own state, stored.
  const banners = (feed.data?.items ?? []).filter((item) => item.show_as_banner && !item.dismissed);
  if (banners.length === 0) return null;
  return (
    <Flex
      vertical
      gap={4}
      data-testid="announcement-banners"
      role="region"
      aria-label={t('announcements.banners')}
    >
      {banners.map((item) => (
        <Alert
          key={item.id}
          banner
          showIcon
          closable
          type={ALERT_TYPE[item.severity]}
          data-testid={`announcement-banner-${item.id}`}
          // A critical notice comes first in the shell's notice stack (D-124).
          data-notice-critical={item.severity === 'critical' ? 'true' : undefined}
          onClose={() => {
            dismiss.mutate(item.id);
          }}
          message={
            <Typography.Text strong>
              {t(`announcement_severity.${item.severity}`)}: {item.title}
            </Typography.Text>
          }
          description={
            <Typography.Paragraph
              ellipsis={{ rows: 2 }}
              style={{
                whiteSpace: 'pre-line',
                marginBottom: 0,
                // Room for the dots below Arabic-script letters: the clamp cuts the rest.
                lineHeight: clampLineHeight(item.body, 1.5715, urduScript),
              }}
            >
              {item.body}
            </Typography.Paragraph>
          }
          action={
            onOpen === undefined ? undefined : (
              <Button
                size="small"
                type="link"
                onClick={() => {
                  onOpen(item.id);
                }}
              >
                {t('announcements.view')}
              </Button>
            )
          }
        />
      ))}
    </Flex>
  );
}
