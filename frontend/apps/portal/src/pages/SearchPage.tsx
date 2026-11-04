import { Button, Empty, Flex, Input, List, Skeleton, Typography } from 'antd';
import { useState, type ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';

import {
  useCatalogSearch,
  usePortalArticleSearch,
  usePortalIncidents,
  usePortalRequests,
} from '@supportx/api-client';
import { textIn, useAppearance, useLabel, useLicence, useLiveAnnouncementFeed } from '@supportx/ui';

import { useDebounced } from '../useDebounced';

// The groups in their default order (Appendix A); the portal settings choose it with WP-032 S2.
const GROUPS = ['items', 'articles', 'announcements', 'requests'] as const;
type Group = (typeof GROUPS)[number];

interface Hit {
  key: string;
  title: ReactNode;
  detail?: ReactNode;
  to?: string;
}

function GroupList({ group, hits, loading }: { group: Group; hits: Hit[]; loading: boolean }) {
  const t = useLabel();
  if (!loading && hits.length === 0) return null;
  return (
    <section aria-labelledby={`search-${group}`} data-testid={`portal-search-${group}`}>
      <Typography.Title level={2} id={`search-${group}`} style={{ fontSize: 18 }}>
        {t(`portal.search.group.${group}`)}
      </Typography.Title>
      {loading ? (
        <Skeleton active paragraph={{ rows: 2 }} />
      ) : (
        <List
          bordered
          dataSource={hits}
          renderItem={(hit) => (
            <List.Item key={hit.key}>
              <Flex vertical gap={2} style={{ minWidth: 0 }}>
                {hit.to === undefined ? (
                  <Typography.Text strong>{hit.title}</Typography.Text>
                ) : (
                  <Link to={hit.to}>
                    <Typography.Text strong>{hit.title}</Typography.Text>
                  </Link>
                )}
                {hit.detail !== undefined && (
                  <Typography.Text type="secondary" ellipsis>
                    {hit.detail}
                  </Typography.Text>
                )}
              </Flex>
            </List.Item>
          )}
        />
      )}
    </section>
  );
}

/**
 * One search box for everything (WP-032 D2, REQ-PRT-003): catalog items, published articles,
 * current announcements and the person's own requests, each from its own search (each keeps
 * its own permission checks, AC2), shown as groups. Nothing found? Report an issue with the
 * words as its subject (AC3).
 */
export function SearchPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const { locale } = useAppearance();
  const licence = useLicence();
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState(params.get('q') ?? '');
  const q = useDebounced(text.trim(), 300);
  const catalog = licence.has('service_request');
  const items = useCatalogSearch(catalog ? q : '');
  const articles = usePortalArticleSearch(q, locale);
  const feed = useLiveAnnouncementFeed(licence.has('incident'));
  const incidents = usePortalIncidents({ q: q === '' ? undefined : q });
  const requests = usePortalRequests(undefined);
  const words = q.toLocaleLowerCase();
  const matches = (value: string | null | undefined) =>
    (value ?? '').toLocaleLowerCase().includes(words);

  const hits: Record<Group, Hit[]> = {
    items: (items.data ?? []).map((item) => ({
      key: item.id,
      title: <bdi dir="auto">{textIn(item.names, locale)}</bdi>,
      detail: textIn(item.summaries, locale),
      to: `/catalog/items/${item.id}`,
    })),
    // The portal's article page comes with WP-034 (lane C): titles and summaries until then.
    articles: (articles.data ?? []).map((row) => ({
      key: row.id,
      title: <bdi dir="auto">{row.title}</bdi>,
      detail: <span dir="ltr">{row.display_id}</span>,
    })),
    announcements:
      q === ''
        ? []
        : (feed.data?.items ?? [])
            .filter((a) => matches(a.title) || matches(a.body))
            .map((a) => ({ key: a.id, title: <bdi dir="auto">{a.title}</bdi>, detail: a.body })),
    requests:
      q === ''
        ? []
        : [
            ...(incidents.data?.pages ?? [])
              .flatMap((page) => page.items)
              .map((r) => ({
                key: r.id,
                title: (
                  <>
                    <span dir="ltr">{r.display_id}</span> · <bdi dir="auto">{r.subject}</bdi>
                  </>
                ),
                detail: t(`portal_status.${r.portal_status}`),
                to: `/requests/${r.id}`,
              })),
            ...(requests.data?.items ?? [])
              .filter((r) => matches(r.subject) || matches(r.display_id))
              .map((r) => ({
                key: r.id,
                title: (
                  <>
                    <span dir="ltr">{r.display_id}</span> · <bdi dir="auto">{r.subject}</bdi>
                  </>
                ),
                detail: t(`portal_status.${r.portal_status}`),
                to: `/service-requests/${r.id}`,
              })),
          ],
  };
  const loading: Record<Group, boolean> = {
    items: catalog && q !== '' && items.isLoading,
    articles: q !== '' && articles.isLoading,
    announcements: false,
    requests: q !== '' && incidents.isLoading,
  };
  const nothing = q !== '' && GROUPS.every((g) => !loading[g] && hits[g].length === 0);

  return (
    <Flex vertical gap={24} data-testid="portal-search">
      <Typography.Title level={1} style={{ margin: 0 }}>
        {t('portal.search.title')}
      </Typography.Title>
      <Input.Search
        size="large"
        allowClear
        autoFocus
        value={text}
        placeholder={t('portal.search.placeholder')}
        aria-label={t('portal.search.label')}
        data-testid="portal-search-input"
        onChange={(event) => {
          setText(event.target.value);
        }}
        onSearch={(value) => {
          setParams(value.trim() === '' ? {} : { q: value.trim() }, { replace: true });
        }}
      />
      {GROUPS.map((group) => (
        <GroupList key={group} group={group} hits={hits[group]} loading={loading[group]} />
      ))}
      {nothing && (
        <Empty description={t('portal.search.nothing')} data-testid="portal-search-nothing">
          <Button
            type="primary"
            onClick={() => void navigate(`/requests/new?subject=${encodeURIComponent(q)}`)}
            data-testid="portal-search-report"
          >
            {t('portal.search.report')}
          </Button>
        </Empty>
      )}
    </Flex>
  );
}
