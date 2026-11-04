import { AppstoreOutlined, BulbOutlined, ExclamationCircleOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Alert, Card, Flex, Input, Statistic, Typography } from 'antd';
import type { ReactNode } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  portalKeys,
  useCatalogItemList,
  usePopularCatalogItems,
  usePortalSummary,
  useSession,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { usePersonalChannel } from '@supportx/realtime';
import {
  brandText,
  useAppearance,
  useLabel,
  useLicence,
  useLiveAnnouncementFeed,
} from '@supportx/ui';

import { Grid } from './catalog/cards';

const ALERT_TYPE = { info: 'info', warning: 'warning', critical: 'error' } as const;

/** One of the three starting points (REQ-PRT-002 AC2). */
function Start({
  to,
  icon,
  title,
  hint,
  testId,
}: {
  to: string;
  icon: ReactNode;
  title: string;
  hint: string;
  testId: string;
}) {
  return (
    <Link to={to} data-testid={testId} style={{ display: 'block' }}>
      <Card hoverable style={{ height: '100%' }}>
        <Flex gap={12} align="flex-start">
          <span aria-hidden style={{ fontSize: 24 }}>
            {icon}
          </span>
          <Flex vertical gap={2}>
            <Typography.Text strong>{title}</Typography.Text>
            <Typography.Text type="secondary">{hint}</Typography.Text>
          </Flex>
        </Flex>
      </Card>
    </Link>
  );
}

/** My open requests by status, approvals waiting and open tasks; live on my channel. */
function Summary({ approvals: showApprovals }: { approvals: boolean }) {
  const t = useLabel();
  const listFormat = useListFormat();
  const summary = usePortalSummary();
  const data = summary.data;
  if (data === undefined) return null;
  const open = data.open_by_status.reduce((n, e) => n + e.count, 0);
  return (
    <section aria-labelledby="summary-heading" data-testid="portal-summary">
      <Typography.Title level={2} id="summary-heading">
        {t('portal.home.summary')}
      </Typography.Title>
      <Flex gap={12} wrap>
        <Link to="/requests" data-testid="portal-summary-open">
          <Card size="small">
            <Statistic title={t('portal.home.open_requests')} value={open} />
            <Typography.Text type="secondary">
              {listFormat(
                data.open_by_status.map(
                  (e) => `${t(`portal_status.${e.status}`)}: ${String(e.count)}`,
                ),
              )}
            </Typography.Text>
          </Card>
        </Link>
        {showApprovals && (
          <Link to="/approvals" data-testid="portal-summary-approvals">
            <Card size="small">
              <Statistic title={t('portal.home.approvals')} value={data.approvals} />
            </Card>
          </Link>
        )}
        {data.tasks > 0 && (
          <Card size="small" data-testid="portal-summary-tasks">
            <Statistic title={t('portal.home.tasks')} value={data.tasks} />
          </Card>
        )}
      </Flex>
    </section>
  );
}

/** Featured and most requested items (REQ-CAT-027), shown when the tenant has the catalog. */
function Items() {
  const t = useLabel();
  const featured = useCatalogItemList({ featured: true });
  const popular = usePopularCatalogItems();
  const featuredItems = (featured.data ?? []).filter((i) => i.enabled).slice(0, 6);
  const shown = new Set(featuredItems.map((i) => i.id));
  const popularItems = (popular.data ?? []).filter((i) => !shown.has(i.id));
  return (
    <>
      {featuredItems.length > 0 && (
        <section aria-labelledby="featured-heading" data-testid="portal-featured">
          <Typography.Title level={2} id="featured-heading">
            {t('portal.home.featured')}
          </Typography.Title>
          <Grid items={featuredItems} />
        </section>
      )}
      {popularItems.length > 0 && (
        <section aria-labelledby="popular-heading" data-testid="portal-popular">
          <Typography.Title level={2} id="popular-heading">
            {t('portal.home.popular')}
          </Typography.Title>
          <Grid items={popularItems} />
        </section>
      )}
    </>
  );
}

/**
 * Portal home (WP-032 D1, REQ-PRT-002): a greeting with one search box, three starting points
 * (report an issue, request something, find an answer), a live summary of my requests,
 * approvals and tasks, featured and most requested items, and the announcements live for me.
 */
export function HomePage() {
  const t = useLabel();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { locale, intlLocale, mode, branding } = useAppearance();
  const session = useSession().data;
  const licence = useLicence();
  const catalog = licence.has('service_request');
  // Anything about my records or approvals: the counts follow within a second (AC1).
  usePersonalChannel(() => {
    void queryClient.invalidateQueries({ queryKey: [...portalKeys.all, 'summary'] });
  });
  const feed = useLiveAnnouncementFeed(licence.has('incident'));
  const items = feed.data?.items ?? [];
  const format = new Intl.DateTimeFormat(intlLocale, { dateStyle: 'medium', timeStyle: 'short' });
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
        <Input.Search
          size="large"
          enterButton
          allowClear
          placeholder={t('portal.search.placeholder')}
          aria-label={t('portal.search.label')}
          data-testid="portal-home-search"
          style={{ marginTop: 16, maxWidth: 640 }}
          onSearch={(value) => {
            const text = value.trim();
            if (text !== '') void navigate(`/search?q=${encodeURIComponent(text)}`);
          }}
        />
      </section>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: 12,
          marginBottom: 32,
        }}
      >
        <Start
          to="/requests/new"
          icon={<ExclamationCircleOutlined />}
          title={t('portal.home.report')}
          hint={t('portal.home.report_hint')}
          testId="portal-start-report"
        />
        {catalog && (
          <Start
            to="/catalog"
            icon={<AppstoreOutlined />}
            title={t('portal.home.request')}
            hint={t('portal.home.request_hint')}
            testId="portal-start-request"
          />
        )}
        <Start
          to="/search"
          icon={<BulbOutlined />}
          title={t('portal.home.answer')}
          hint={t('portal.home.answer_hint')}
          testId="portal-start-answer"
        />
      </div>
      <Flex vertical gap={32} style={{ marginBottom: 32 }}>
        <Summary approvals={catalog} />
        {catalog && <Items />}
      </Flex>
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
