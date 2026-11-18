import { Alert, Button, Card, Empty, Flex, List, Select, Skeleton, Space, Typography } from 'antd';
import { useMemo, useState, type ReactNode } from 'react';

import {
  useCiAsOf,
  useCiCompare,
  useCiStates,
  useCiTypes,
  useCiVersions,
  useRelationshipTypes,
  type CiAttributeChange,
  type CiVersion,
  type CiVersionLink,
  type RelationshipType,
} from '@supportx/api-client';
import {
  DateTimeField,
  PropertyList,
  ToneTag,
  useAppearance,
  useDateTime,
  useLabel,
  type Tone,
} from '@supportx/ui';

import { nameOf } from '../names';
import { nodeName, relationshipName } from './words';

/** Text longer than this is shortened behind "Show all" (condition 13). */
export const SHORT_TEXT = 160;

/** Fields whose value is another record's ID: never shown raw (CLAUDE.md rule d). */
const REFERENCE_FIELDS = new Set([
  'site_id',
  'owner_user_id',
  'owner_group_id',
  'managed_by_group_id',
  'asset_id',
]);

const KIND_TONE: Record<CiAttributeChange['kind'], Tone> = {
  added: 'success',
  removed: 'error',
  changed: 'info',
};

/**
 * The CI's Versions tab (template A; REQ-CMDB-024's view side; lane C's condition 13): every
 * saved version, the CI "as of" a time (picked in the person's zone, sent as UTC), and two
 * versions compared, grouped as attributes and relationships. Values read as on the record:
 * states, types and codes by label, other records never by their ID, long text shortened.
 * The server answers with the reader's current rights: hidden fields never come.
 */
export function VersionsTab({ ciId }: { ciId: string }) {
  const t = useLabel();
  const dates = useDateTime();
  const versions = useCiVersions(ciId);
  const items = versions.data?.pages.flatMap((p) => p.items) ?? [];
  const [at, setAt] = useState<string | null>(null);
  const [pair, setPair] = useState<{ from?: number; to?: number }>({});
  const [compared, setCompared] = useState<{ from: number; to: number } | null>(null);
  const options = items.map((v) => ({
    value: v.version,
    label: t('cmdb.versions.option', { version: v.version, at: dates.format(v.saved_at) }),
  }));

  return (
    <Flex vertical gap={16} data-testid="ci-versions">
      <Card size="small" title={t('cmdb.versions.list')}>
        {versions.isPending ? (
          <Skeleton active />
        ) : (
          <List
            size="small"
            dataSource={items}
            locale={{ emptyText: <Empty description={t('cmdb.versions.none')} /> }}
            data-testid="ci-versions-list"
            renderItem={(v) => (
              <List.Item data-testid={`ci-version-${String(v.version)}`}>
                <Typography.Text>
                  <bdi>{t('cmdb.versions.number', { version: v.version })}</bdi> ·{' '}
                  <bdi>{dates.format(v.saved_at)}</bdi>
                  {v.saved_by_name !== null && (
                    <>
                      {' · '}
                      <bdi>{v.saved_by_name}</bdi>
                    </>
                  )}
                </Typography.Text>
              </List.Item>
            )}
          />
        )}
        {versions.hasNextPage && (
          <Button
            size="small"
            loading={versions.isFetchingNextPage}
            onClick={() => void versions.fetchNextPage()}
          >
            {t('cmdb.more')}
          </Button>
        )}
      </Card>

      <Card size="small" title={t('cmdb.versions.as_of')}>
        <Flex vertical gap={12}>
          <div style={{ maxWidth: 320 }}>
            <DateTimeField value={at} onChange={setAt} testId="ci-versions-as-of" />
          </div>
          {at !== null && <AsOf ciId={ciId} at={at} />}
        </Flex>
      </Card>

      <Card size="small" title={t('cmdb.versions.compare')}>
        <Flex vertical gap={12}>
          <Space wrap>
            <Select<number>
              aria-label={t('cmdb.versions.compare_from')}
              placeholder={t('cmdb.versions.compare_from')}
              value={pair.from}
              onChange={(from) => {
                setPair((p) => ({ ...p, from }));
              }}
              options={options}
              style={{ minWidth: 240 }}
              data-testid="ci-versions-from"
            />
            <Select<number>
              aria-label={t('cmdb.versions.compare_to')}
              placeholder={t('cmdb.versions.compare_to')}
              value={pair.to}
              onChange={(to) => {
                setPair((p) => ({ ...p, to }));
              }}
              options={options}
              style={{ minWidth: 240 }}
              data-testid="ci-versions-to"
            />
            <Button
              type="primary"
              disabled={pair.from === undefined || pair.to === undefined || pair.from === pair.to}
              onClick={() => {
                if (pair.from !== undefined && pair.to !== undefined) {
                  setCompared({
                    from: Math.min(pair.from, pair.to),
                    to: Math.max(pair.from, pair.to),
                  });
                }
              }}
              data-testid="ci-versions-compare"
            >
              {t('cmdb.versions.compare_action')}
            </Button>
          </Space>
          {compared !== null && <Comparison ciId={ciId} pair={compared} />}
        </Flex>
      </Card>
    </Flex>
  );
}

/** A field's value as the record shows it. */
function useValueText() {
  const t = useLabel();
  const { locale } = useAppearance();
  const types = useCiTypes();
  const states = useCiStates();
  return (field: string, value: unknown): string => {
    if (value === null || value === undefined || value === '') return t('cmdb.versions.empty');
    // A sealed value (ADR-050) stays sealed in every version, as on the record.
    if (typeof value === 'object' && (value as { sealed?: unknown }).sealed === true) {
      return t('cmdb.versions.sealed');
    }
    if (field === 'type_id') {
      const type = types.data?.items.find((x) => x.id === value);
      return type === undefined
        ? t('cmdb.versions.unknown')
        : nameOf(t, locale, type, 'cmdb_ci_type');
    }
    if (field === 'state_id') {
      const state = states.data?.items.find((x) => x.id === value);
      return state === undefined
        ? t('cmdb.versions.unknown')
        : nameOf(t, locale, state, 'cmdb_ci_state');
    }
    // Codes by their labels; another record never by its ID (rule d).
    const code = typeof value === 'string' ? value : '';
    if (field === 'business_impact' || field === 'criticality') return t(`cmdb_impact.${code}`);
    if (field === 'source') return t(`cmdb_ci_source.${code}`);
    if (REFERENCE_FIELDS.has(field)) return t('cmdb.versions.set');
    if (typeof value === 'string') return value;
    return typeof value === 'number' ? String(value) : t('cmdb.versions.set');
  };
}

/** Long text shortened behind "Show all". */
export function LongText({ text }: { text: string }) {
  const t = useLabel();
  const [open, setOpen] = useState(false);
  if (text.length <= SHORT_TEXT) return <bdi style={{ whiteSpace: 'pre-wrap' }}>{text}</bdi>;
  return (
    <span>
      <bdi style={{ whiteSpace: 'pre-wrap' }}>{open ? text : `${text.slice(0, SHORT_TEXT)}…`}</bdi>{' '}
      <Button
        type="link"
        size="small"
        onClick={() => {
          setOpen((o) => !o);
        }}
        aria-expanded={open}
        data-testid="long-text-toggle"
      >
        {open ? t('cmdb.versions.show_less') : t('cmdb.versions.show_all')}
      </Button>
    </span>
  );
}

function useLinkText(types: readonly RelationshipType[]) {
  const t = useLabel();
  const { locale } = useAppearance();
  const byId = useMemo(() => new Map(types.map((x) => [x.id, x])), [types]);
  return (link: CiVersionLink): ReactNode => (
    <>
      <bdi>{relationshipName(t, locale, byId.get(link.type_id), link.direction)}</bdi>{' '}
      <bdi>
        {nodeName(t, link.ci)}
        {!link.ci.restricted && link.ci.display_id != null ? ` (${link.ci.display_id})` : ''}
      </bdi>
    </>
  );
}

function VersionBody({ version }: { version: CiVersion }) {
  const t = useLabel();
  const dates = useDateTime();
  const value = useValueText();
  const types = useRelationshipTypes();
  const linkText = useLinkText(types.data?.items ?? []);
  return (
    <Flex vertical gap={12} data-testid="ci-versions-as-of-result">
      <Typography.Text type="secondary">
        {t('cmdb.versions.number', { version: version.version })} ·{' '}
        <bdi>{dates.format(version.saved_at)}</bdi>
      </Typography.Text>
      <PropertyList
        items={Object.entries(version.fields).map(([field, v]) => ({
          key: field,
          label: t(`cmdb.field.${field}`),
          content: <LongText text={value(field, v)} />,
          filled: true,
        }))}
      />
      <Typography.Text strong>{t('cmdb.field.relationships')}</Typography.Text>
      {version.relationships.length === 0 ? (
        <Typography.Text type="secondary">{t('cmdb.versions.no_relationships')}</Typography.Text>
      ) : (
        <List
          size="small"
          dataSource={version.relationships}
          renderItem={(link) => <List.Item>{linkText(link)}</List.Item>}
        />
      )}
    </Flex>
  );
}

function AsOf({ ciId, at }: { ciId: string; at: string }) {
  const found = useCiAsOf(ciId, at);
  const t = useLabel();
  if (found.isPending) return <Skeleton active />;
  if (found.isError) {
    return <Alert type="info" showIcon message={t('errors.cmdb_ci_version_not_found')} />;
  }
  return <VersionBody version={found.data} />;
}

/** Two versions compared: attributes, then relationships added and removed (condition 13). */
export function Comparison({ ciId, pair }: { ciId: string; pair: { from: number; to: number } }) {
  const t = useLabel();
  const value = useValueText();
  const found = useCiCompare(ciId, pair);
  const types = useRelationshipTypes();
  const linkText = useLinkText(types.data?.items ?? []);
  if (found.isPending) return <Skeleton active />;
  if (found.isError)
    return <Alert type="info" showIcon message={t('errors.cmdb_ci_version_not_found')} />;
  const result = found.data;
  const links = [
    ...result.relationships_added.map((link) => ({ kind: 'added' as const, link })),
    ...result.relationships_removed.map((link) => ({ kind: 'removed' as const, link })),
  ];
  return (
    <Flex vertical gap={16} data-testid="ci-versions-comparison">
      <section aria-label={t('cmdb.versions.attributes')} data-testid="ci-compare-attributes">
        <Typography.Title level={5}>{t('cmdb.versions.attributes')}</Typography.Title>
        {result.attributes.length === 0 ? (
          <Typography.Text type="secondary">{t('cmdb.versions.no_changes')}</Typography.Text>
        ) : (
          <List
            size="small"
            dataSource={result.attributes}
            renderItem={(change) => (
              <List.Item data-testid={`ci-compare-${change.field}`}>
                <Flex vertical gap={4} style={{ width: '100%' }}>
                  <Space wrap>
                    <Typography.Text strong>{t(`cmdb.field.${change.field}`)}</Typography.Text>
                    <ToneTag tone={KIND_TONE[change.kind]}>
                      {t(`cmdb_compare_kind.${change.kind}`)}
                    </ToneTag>
                  </Space>
                  {change.kind !== 'added' && (
                    <Typography.Text type="secondary">
                      {t('cmdb.versions.before')}{' '}
                      <LongText text={value(change.field, change.old)} />
                    </Typography.Text>
                  )}
                  {change.kind !== 'removed' && (
                    <Typography.Text>
                      {t('cmdb.versions.after')} <LongText text={value(change.field, change.new)} />
                    </Typography.Text>
                  )}
                </Flex>
              </List.Item>
            )}
          />
        )}
      </section>
      <section aria-label={t('cmdb.field.relationships')} data-testid="ci-compare-relationships">
        <Typography.Title level={5}>{t('cmdb.field.relationships')}</Typography.Title>
        {links.length === 0 ? (
          <Typography.Text type="secondary">{t('cmdb.versions.no_changes')}</Typography.Text>
        ) : (
          <List
            size="small"
            dataSource={links}
            renderItem={({ kind, link }) => (
              <List.Item>
                <Space wrap>
                  <ToneTag tone={KIND_TONE[kind]}>{t(`cmdb_compare_kind.${kind}`)}</ToneTag>
                  <span>{linkText(link)}</span>
                </Space>
              </List.Item>
            )}
          />
        )}
      </section>
    </Flex>
  );
}
