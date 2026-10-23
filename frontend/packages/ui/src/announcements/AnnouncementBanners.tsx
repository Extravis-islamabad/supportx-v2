import { Alert, Button, Flex, Typography } from 'antd';
import { useState } from 'react';

import type { AnnouncementPublic } from '@supportx/api-client';

import { useLabel } from '../appearance';
import { useLiveAnnouncementFeed } from './useLiveAnnouncementFeed';

const ALERT_TYPE = { info: 'info', warning: 'warning', critical: 'error' } as const;
const DISMISSED_KEY = 'supportx.announcements.dismissed';

/** Dismissed banners, per browser (a convenience: the announcement is still in the list). */
function readDismissed(): Set<string> {
  try {
    const raw = window.localStorage.getItem(DISMISSED_KEY);
    return new Set(raw === null ? [] : (JSON.parse(raw) as string[]));
  } catch {
    return new Set();
  }
}

function writeDismissed(keys: Set<string>): void {
  try {
    // Keep the newest 100 only: old announcements end anyway.
    window.localStorage.setItem(DISMISSED_KEY, JSON.stringify([...keys].slice(-100)));
  } catch {
    // Private mode or storage blocked: dismissing just lasts until the page reloads.
  }
}

/** A republished announcement shows again, so the key includes when it was published. */
const dismissKey = (item: AnnouncementPublic) => `${item.id}@${item.published_at ?? ''}`;

export interface AnnouncementBannersProps {
  /** Whether this tenant's plan includes announcements (no calls otherwise). */
  enabled?: boolean;
  /** Where "View" goes (console: the announcement page); without it there is no link. */
  onOpen?: (id: string) => void;
}

/** Banners for live announcements marked "show as banner", above every page of the app. */
export function AnnouncementBanners({ enabled = true, onOpen }: AnnouncementBannersProps) {
  const t = useLabel();
  const feed = useLiveAnnouncementFeed(enabled);
  const [dismissed, setDismissed] = useState(readDismissed);
  const banners = (feed.data?.items ?? []).filter(
    (item) => item.show_as_banner && !dismissed.has(dismissKey(item)),
  );
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
          onClose={() => {
            const next = new Set(dismissed).add(dismissKey(item));
            writeDismissed(next);
            setDismissed(next);
          }}
          message={
            <Typography.Text strong>
              {t(`announcement_severity.${item.severity}`)}: {item.title}
            </Typography.Text>
          }
          description={
            <Typography.Paragraph
              ellipsis={{ rows: 2 }}
              style={{ whiteSpace: 'pre-line', marginBottom: 0 }}
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
