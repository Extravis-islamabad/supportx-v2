import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Flex,
  Popconfirm,
  Skeleton,
  Tabs,
  Tag,
  Timeline,
  Typography,
} from 'antd';
import { useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router';

import {
  queryKeys,
  useAssetHistory,
  useAssetProductTypes,
  useAssetRecord,
  useAssetRecordChange,
  useAssetStates,
  useSession,
  type AssetRecord,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { useRecordChannel } from '@supportx/realtime';
import {
  NoAccess,
  PageHeader,
  PresenceAvatars,
  reportError,
  useAccess,
  useAppearance,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { Problems } from '../admin/incidents/shared';
import { nameOf } from '../admin/assets/shared';
import { CopyAssetDialog, MoveAssetDialog } from './AssetActions';
import { AssetFields } from './AssetForm';
import { bodyOf, draftOf, type AssetDraft } from './draft';
import { useAssetSaveProblems } from './problems';

// The record's tabs, always in this order (REQ-AST-001 AC3): later sessions add theirs here.
const TABS = ['details', 'history'] as const;
type TabKey = (typeof TABS)[number];
const HISTORY_FIELDS = new Set([
  'name',
  'product_id',
  'product_type_id',
  'state_id',
  'tag',
  'serial_number',
  'barcode',
  'vendor_id',
  'site_id',
  'location',
  'purchase_price',
  'purchase_tax',
  'currency',
  'acquired_on',
  'warranty_expires_on',
  'expires_on',
  'description',
  'deleted',
]);

/**
 * One asset (WP-049a s2): its details, editable with If-Match, and its history. Another
 * person's save arrives live through the asset's channel: an untouched page shows it at once;
 * with unsaved edits the page says so and keeps them, and the save is then refused (409) rather
 * than writing over the other change.
 */
export function AssetPage() {
  const t = useLabel();
  const { id } = useParams();
  const access = useAccess();
  const asset = useAssetRecord(access.can('assets.view') ? id : undefined);
  if (!access.can('assets.view')) return <NoAccess titleKey="nav.assets" />;
  if (asset.isLoading) return <Skeleton active />;
  if (asset.data === undefined) {
    return (
      <Alert
        type="warning"
        showIcon
        message={t('errors.asset_not_found')}
        data-testid="asset-missing"
      />
    );
  }
  return <AssetView asset={asset.data} />;
}

function AssetView({ asset }: { asset: AssetRecord }) {
  const t = useLabel();
  const { locale, intlLocale } = useAppearance();
  const access = useAccess();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const me = useSession().data?.user.id;
  const [params, setParams] = useSearchParams();
  const tab: TabKey = TABS.includes(params.get('tab') as TabKey)
    ? (params.get('tab') as TabKey)
    : 'details';
  const types = useAssetProductTypes();
  const states = useAssetStates();
  const change = useAssetRecordChange();
  const { problems, show, clear } = useAssetSaveProblems();
  const [editing, setEditing] = useState<{ draft: AssetDraft; base: number }>();
  const [changedElsewhere, setChangedElsewhere] = useState(false);
  const [dialog, setDialog] = useState<'move' | 'copy'>();
  const viewers = useRecordChannel('asset', asset.id, (event) => {
    if (event.version !== undefined && event.version <= asset.version) return; // our own save
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.history(asset.id) });
    if (editing === undefined) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.record(asset.id) });
    } else {
      setChangedElsewhere(true);
    }
  });
  const manage = access.can('assets.manage');
  const type = types.data?.find((x) => x.id === asset.product_type_id);
  const state = states.data?.find((x) => x.id === asset.state_id);
  const money = (amount: string | null | undefined) =>
    amount === null || amount === undefined
      ? '—'
      : asset.currency === null
        ? new Intl.NumberFormat(intlLocale, { minimumFractionDigits: 2 }).format(Number(amount))
        : new Intl.NumberFormat(intlLocale, { style: 'currency', currency: asset.currency }).format(
            Number(amount),
          );
  const save = () => {
    if (editing === undefined) return;
    clear();
    const body = bodyOf(editing.draft, draftOf(asset));
    change.mutate(
      { kind: 'update', id: asset.id, version: editing.base, body },
      {
        onSuccess: () => {
          setEditing(undefined);
          setChangedElsewhere(false);
        },
        onError: show,
      },
    );
  };
  const details = editing ? (
    <Card>
      {changedElsewhere && (
        <Alert
          type="warning"
          showIcon
          message={t('assets.record.changed_elsewhere')}
          style={{ marginBottom: 12 }}
          data-testid="asset-changed-elsewhere"
        />
      )}
      <Problems problems={problems} testId="asset-edit-problems" />
      <AssetFields
        creating={false}
        draft={editing.draft}
        onChange={(draft) => {
          setEditing({ ...editing, draft });
        }}
      />
      <Flex gap={8}>
        <WriteButton
          type="primary"
          loading={change.isPending}
          onClick={save}
          data-testid="asset-save"
        >
          {t('actions.save')}
        </WriteButton>
        <Button
          onClick={() => {
            setEditing(undefined);
            clear();
          }}
        >
          {t('actions.cancel')}
        </Button>
      </Flex>
    </Card>
  ) : (
    <Card
      extra={
        manage && (
          <WriteButton
            onClick={() => {
              setEditing({ draft: draftOf(asset), base: asset.version });
              setChangedElsewhere(false);
            }}
            data-testid="asset-edit"
          >
            {t('actions.edit')}
          </WriteButton>
        )
      }
    >
      <Descriptions
        column={{ xs: 1, md: 2 }}
        size="small"
        items={[
          { key: 'tag', label: t('assets.record.tag'), children: <bdi dir="ltr">{asset.tag}</bdi> },
          {
            key: 'type',
            label: t('assets.admin.product_type'),
            children: <bdi dir="auto">{type === undefined ? '' : nameOf(type.names, locale)}</bdi>,
          },
          {
            key: 'serial',
            label: t('assets.record.serial_number'),
            children: <bdi dir="ltr">{asset.serial_number ?? '—'}</bdi>,
          },
          {
            key: 'barcode',
            label: t('assets.record.barcode'),
            children: <bdi dir="ltr">{asset.barcode ?? '—'}</bdi>,
          },
          {
            key: 'price',
            label: t('assets.record.purchase_price'),
            children: money(asset.purchase_price),
          },
          {
            key: 'tax',
            label: t('assets.record.purchase_tax'),
            children: money(asset.purchase_tax),
          },
          {
            key: 'total',
            label: t('assets.admin.total'),
            children: <span data-testid="asset-total">{money(asset.purchase_total)}</span>,
          },
          {
            key: 'acquired',
            label: t('assets.record.acquired_on'),
            children: asset.acquired_on ?? '—',
          },
          {
            key: 'warranty',
            label: t('assets.record.warranty_expires_on'),
            children: asset.warranty_expires_on ?? '—',
          },
          {
            key: 'location',
            label: t('assets.record.location'),
            children: <bdi dir="auto">{asset.location ?? '—'}</bdi>,
          },
        ]}
      />
      {asset.description !== null && (
        <Typography.Paragraph style={{ marginTop: 12, whiteSpace: 'pre-wrap' }}>
          <bdi dir="auto">{asset.description}</bdi>
        </Typography.Paragraph>
      )}
    </Card>
  );
  return (
    <Flex vertical gap={16}>
      <PageHeader
        title={<bdi dir="auto">{asset.name}</bdi>}
        extra={
          <Flex gap={8} align="center">
            <PresenceAvatars viewers={viewers} selfUserId={me ?? null} />
            {state !== undefined && (
              <Tag data-testid="asset-state">{nameOf(state.names, locale)}</Tag>
            )}
            {manage && (
              <WriteButton
                onClick={() => {
                  setDialog('move');
                }}
                data-testid="asset-move-open"
              >
                {t('assets.move.open')}
              </WriteButton>
            )}
            {manage && (
              <WriteButton
                onClick={() => {
                  setDialog('copy');
                }}
                data-testid="asset-copy-open"
              >
                {t('assets.copy.open')}
              </WriteButton>
            )}
            {manage && (
              <Popconfirm
                title={t('assets.record.trash_confirm')}
                okText={t('actions.delete')}
                cancelText={t('actions.cancel')}
                onConfirm={() => {
                  change.mutate(
                    { kind: 'delete', id: asset.id, version: asset.version },
                    {
                      onSuccess: () => void navigate('/assets'),
                      onError: reportError,
                    },
                  );
                }}
              >
                <Button danger data-testid="asset-trash">
                  {t('actions.delete')}
                </Button>
              </Popconfirm>
            )}
          </Flex>
        }
      />
      <MoveAssetDialog
        asset={asset}
        open={dialog === 'move'}
        onClose={() => {
          setDialog(undefined);
        }}
      />
      <CopyAssetDialog
        asset={asset}
        open={dialog === 'copy'}
        onClose={() => {
          setDialog(undefined);
        }}
      />
      <Tabs
        activeKey={tab}
        onChange={(key) => {
          setParams({ tab: key }, { replace: true });
        }}
        items={[
          { key: 'details', label: t('assets.record.details'), children: details },
          {
            key: 'history',
            label: t('assets.record.history'),
            children: <AssetHistory id={asset.id} />,
          },
        ]}
        data-testid="asset-tabs"
      />
    </Flex>
  );
}

function AssetHistory({ id }: { id: string }) {
  const t = useLabel();
  const { intlLocale } = useAppearance();
  const history = useAssetHistory(id);
  const list = useListFormat();
  const entries = history.data?.pages.flatMap((p) => p.items) ?? [];
  // Field codes never show (§5d): each known one by its label, a custom field as such.
  const field = (name: string) =>
    name.startsWith('custom.')
      ? t('assets.record.custom_field')
      : HISTORY_FIELDS.has(name)
        ? t(`assets.record.${name}`)
        : t('assets.record.other_field');
  return (
    <Card>
      <Timeline
        items={entries.map((entry) => ({
          key: entry.version,
          children: (
            <Flex vertical gap={2} data-testid={`asset-history-${String(entry.version)}`}>
              <Typography.Text type="secondary">
                {new Intl.DateTimeFormat(intlLocale, {
                  dateStyle: 'medium',
                  timeStyle: 'short',
                }).format(new Date(entry.occurred_at))}
                {' · '}
                <bdi dir="auto">{entry.actor_name ?? t('assets.record.someone')}</bdi>
              </Typography.Text>
              <span>
                {entry.kind === 'created'
                  ? t('assets.record.history_created')
                  : list([...new Set(entry.changes.map((c) => field(c.field)))])}
              </span>
            </Flex>
          ),
        }))}
      />
      {history.hasNextPage && (
        <Button
          onClick={() => {
            void history.fetchNextPage();
          }}
        >
          {t('assets.admin.load_more')}
        </Button>
      )}
    </Card>
  );
}
