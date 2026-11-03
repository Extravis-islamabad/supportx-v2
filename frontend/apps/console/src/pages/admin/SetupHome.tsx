import { Card, Col, Empty, Input, Row, Space, Typography } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import { useAccess, useLabel } from '@supportx/ui';

import { matches, pagesFor, SETUP_GROUPS, type SetupPage } from './setupMap';

/** What a page is found by: its name, its one-line description and its keywords. */
function useSetupText() {
  const t = useLabel();
  return (page: SetupPage) => [
    t(page.labelKey),
    t(`setup.page.${page.key}.description`),
    t(`setup.page.${page.key}.keywords`),
    t(`setup.group.${page.group}`),
  ];
}

/**
 * The setup home (WP-042, REQ-ADM-106, 107): every page this person may open, grouped by task,
 * each with a one-line explanation, and a search over names, explanations and keywords.
 */
export function SetupHome() {
  const t = useLabel();
  const { can } = useAccess();
  const text = useSetupText();
  const [query, setQuery] = useState('');
  const pages = pagesFor(can).filter((page) => matches(query, text(page)));

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }} data-testid="setup-home">
      <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
        {t('setup.intro')}
      </Typography.Paragraph>
      <Input.Search
        allowClear
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
        placeholder={t('setup.search_placeholder')}
        aria-label={t('setup.search')}
        data-testid="setup-search"
        style={{ maxWidth: 480 }}
      />
      {pages.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t('setup.no_results', { query })}
          data-testid="setup-no-results"
        />
      ) : (
        SETUP_GROUPS.map((group) => {
          const inGroup = pages.filter((page) => page.group === group);
          if (inGroup.length === 0) return null;
          return (
            <section key={group} aria-labelledby={`setup-home-${group}`}>
              <Typography.Title level={2} id={`setup-home-${group}`} style={{ fontSize: 16 }}>
                {t(`setup.group.${group}`)}
              </Typography.Title>
              <Row gutter={[16, 16]}>
                {inGroup.map((page) => (
                  <Col key={page.key} xs={24} md={12} xl={8}>
                    <Card size="small" style={{ height: '100%' }}>
                      <Link to={`/admin/${page.key}`} data-testid={`setup-page-${page.key}`}>
                        <Typography.Text strong>{t(page.labelKey)}</Typography.Text>
                      </Link>
                      <Typography.Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
                        {t(`setup.page.${page.key}.description`)}
                      </Typography.Paragraph>
                    </Card>
                  </Col>
                ))}
              </Row>
            </section>
          );
        })
      )}
    </Space>
  );
}
