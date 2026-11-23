import { Col, Flex, List, Row, Skeleton, Typography } from 'antd';
import { useNavigate } from 'react-router';

import { useSecurityOverview, type SecurityFlag } from '@supportx/api-client';
import {
  KpiTile,
  SettingsCard,
  ToneTag,
  useAppearance,
  useDateTime,
  useLabel,
  type Tone,
} from '@supportx/ui';

// WP-057 S4d: the security screens' numbers at a glance, at the top of Admin › Sign-in and
// security, with the weaker-than-recommended choices first. Every number is the one its own
// card or page shows (the server reads the same services); each tile and flag leads there,
// where that page's own rights apply. Counts and codes only, never a name or an address.

const SEVERITY_TONE: Record<SecurityFlag['severity'], Tone> = {
  high: 'error',
  medium: 'warning',
  low: 'default',
};

type Area = SecurityFlag['area'];

/** Where each area's detail is: a card on this page (by its test id), or another page. */
const AREA_TARGET: Record<Area, { card?: string; path?: string }> = {
  mfa: { card: 'security-mfa' },
  sign_in: { card: 'security-sso' },
  passwords: { card: 'security-password' },
  sessions: { card: 'security-sessions' },
  network: { card: 'security-network' },
  keys: { path: '/admin/api-keys' },
  service_accounts: { path: '/admin/service-accounts' },
  encryption: {},
  sign_in_events: { path: '/admin/audit?tab=sign_ins' },
  // WP-057 S4c: the vendor support card comes with S4c-3; until then the flag links nowhere.
  vendor_support: {},
  // D-181: plaintext syslog destinations, on the audit page's Security monitoring tab.
  siem: { path: '/admin/audit?tab=siem' },
};

function useOpen() {
  const navigate = useNavigate();
  return (area: Area): (() => void) | undefined => {
    const target = AREA_TARGET[area];
    if (target.path !== undefined) {
      const path = target.path;
      return () => {
        void navigate(path);
      };
    }
    if (target.card !== undefined) {
      const card = target.card;
      return () => {
        const found = document.querySelector<HTMLElement>(`[data-testid="${card}"]`);
        found?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        found?.focus({ preventScroll: true });
      };
    }
    return undefined;
  };
}

/** The overview card: tiles, then the flags, most severe first. */
export function SecurityOverview() {
  const t = useLabel();
  const { intlLocale } = useAppearance();
  const dates = useDateTime();
  const found = useSecurityOverview();
  const open = useOpen();
  const number = new Intl.NumberFormat(intlLocale);
  const n = (value: number) => number.format(value);
  const data = found.data;
  if (data === undefined) {
    return (
      <SettingsCard title={t('security.overview.title')} testId="security-overview">
        <Skeleton active paragraph={{ rows: 3 }} />
      </SettingsCard>
    );
  }
  const sealed = data.seal_states.sealed ?? 0;
  const moving = (data.seal_states.sealing ?? 0) + (data.seal_states.opening ?? 0);
  const tiles: {
    key: Area | 'region';
    label: string;
    value: string;
    hint?: string;
    tone?: 'default' | 'danger' | 'warning' | 'success';
  }[] = [
    {
      key: 'mfa',
      label: t('security_area.mfa'),
      value: `${n(data.mfa.enrolled)} / ${n(data.mfa.holders)}`,
      hint: t('security.overview.mfa_hint', { required: n(data.mfa.roles_required) }),
    },
    {
      key: 'sign_in',
      label: t('security_area.sign_in'),
      value: t(`security.overview.sso_required.${data.sso_required}`),
      hint:
        data.sso_expiry_days_left === null
          ? t('security.overview.sso_setups', { n: n(data.sso_setups) })
          : t('security.overview.sso_expiry', { days: n(data.sso_expiry_days_left) }),
      tone:
        data.sso_expiry_days_left !== null && data.sso_expiry_days_left <= 7 ? 'danger' : 'default',
    },
    // Tiles the viewer may not open come back null (lane B, #537): they are left out here.
    ...(data.keys === null
      ? []
      : [
          {
            key: 'keys' as const,
            label: t('security_area.keys'),
            value: n(data.keys.active),
            hint: t('security.overview.keys_hint', {
              out: n(data.keys.out_of_policy),
              unused: n(data.keys.unused),
            }),
            tone: data.keys.out_of_policy > 0 ? ('warning' as const) : ('default' as const),
          },
        ]),
    ...(data.service_accounts === null
      ? []
      : [
          {
            key: 'service_accounts' as const,
            label: t('security_area.service_accounts'),
            value: n(data.service_accounts),
            hint: t('security.overview.owners_hint', {
              n: n(data.service_accounts_without_owner ?? 0),
            }),
            tone:
              (data.service_accounts_without_owner ?? 0) > 0
                ? ('warning' as const)
                : ('default' as const),
          },
        ]),
    {
      key: 'encryption',
      label: t('security_area.encryption'),
      value: n(sealed),
      hint:
        moving > 0
          ? t('security.overview.fields_moving', { n: n(moving) })
          : data.key_since === null
            ? t('security.overview.no_key')
            : t('security.overview.key_since', { when: dates.relative(data.key_since) }),
    },
    ...(data.failed_sign_ins === null
      ? []
      : [
          {
            key: 'sign_in_events' as const,
            label: t('security_area.sign_in_events'),
            value: n(data.failed_sign_ins),
            hint: t('security.overview.locked_hint', { n: n(data.locked_sign_ins ?? 0) }),
            tone: (data.locked_sign_ins ?? 0) > 0 ? ('warning' as const) : ('default' as const),
          },
        ]),
  ];
  if (data.data_region !== null) {
    // The installation's own statement, read only; absent when blank (never "unknown").
    tiles.push({
      key: 'region',
      label: t('security.overview.region'),
      value: data.data_region,
    });
  }
  return (
    <SettingsCard
      title={t('security.overview.title')}
      description={t('security.overview.help')}
      testId="security-overview"
    >
      <Flex vertical gap={16}>
        <Row gutter={[12, 12]}>
          {tiles.map((tile) => (
            <Col key={tile.key} xs={12} md={8} xl={6}>
              <KpiTile
                label={tile.label}
                value={<bdi>{tile.value}</bdi>}
                hint={tile.hint}
                tone={tile.tone}
                onClick={tile.key === 'region' ? undefined : open(tile.key)}
                testId={`security-tile-${tile.key}`}
              />
            </Col>
          ))}
        </Row>
        <div>
          <Typography.Title level={5} id="security-flags-title" style={{ marginTop: 0 }}>
            {t('security.overview.flags')}
          </Typography.Title>
          {data.flags.length === 0 ? (
            <Typography.Text type="secondary" data-testid="security-flags-none">
              {t('security.overview.no_flags')}
            </Typography.Text>
          ) : (
            <List
              size="small"
              aria-labelledby="security-flags-title"
              data-testid="security-flags"
              dataSource={data.flags}
              renderItem={(flag) => {
                const go = open(flag.area);
                return (
                  <List.Item data-testid={`security-flag-${flag.code}`}>
                    <Flex gap={8} align="center" wrap>
                      <ToneTag tone={SEVERITY_TONE[flag.severity]}>
                        {t(`security_severity.${flag.severity}`)}
                      </ToneTag>
                      <Typography.Text>
                        {t(`security_flag.${flag.code}`, {
                          count: flag.count === null ? '' : n(flag.count),
                        })}
                      </Typography.Text>
                      {go !== undefined && (
                        <Typography.Link
                          onClick={go}
                          data-testid={`security-flag-open-${flag.code}`}
                        >
                          {t('security.overview.open', { area: t(`security_area.${flag.area}`) })}
                        </Typography.Link>
                      )}
                    </Flex>
                  </List.Item>
                );
              }}
            />
          )}
          <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            {t('security.overview.recommendations_note')}
          </Typography.Paragraph>
        </div>
      </Flex>
    </SettingsCard>
  );
}
