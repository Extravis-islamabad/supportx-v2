import { CopyOutlined, EditOutlined, LaptopOutlined, SwapOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Card, Flex, Skeleton, Tabs, Timeline, Typography } from 'antd';
import dayjs from 'dayjs';
import { useState, type ReactNode } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router';

import {
  queryKeys,
  useAssetHistory,
  useAssetProductTypes,
  useAssetRecord,
  useAssetMoves,
  useAssetSettings,
  useCustomFields,
  useAssetRecordChange,
  useAssetStates,
  useSession,
  type AssetRecord,
  type AssetState,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { useRecordChannel } from '@supportx/realtime';
import {
  ActionBar,
  EditableValue,
  EmptyText,
  NoAccess,
  PresenceAvatars,
  PropertiesPanel,
  PropertyList,
  RecordHeader,
  RecordPage,
  reportError,
  ToneTag,
  useAccess,
  useAppearance,
  useDateTime,
  useLabel,
  WriteButton,
  type PanelSection,
  type PropertyItem,
  type RecordAction,
  type Tone,
} from '@supportx/ui';

import { Problems } from '../admin/incidents/shared';
import { nameOf } from '../admin/assets/shared';
import { CustomFieldValue } from '../customFields/fields';
import { fieldName } from '../customFields/values';
import { CopyAssetDialog, MoveAssetDialog } from './AssetActions';
import { AssetRelations } from './AssetRelations';
import { ageBetween, basisDay } from './age';
import { DisposalCard, DisposeAssetDialog } from './Disposal';
import { AssetFields } from './AssetForm';
import { bodyOf, draftOf, type AssetDraft } from './draft';
import { useAssetSaveProblems } from './problems';

// The record's tabs, always in this order (REQ-AST-001 AC3): later sessions add theirs here.
const TABS = ['details', 'relations', 'history'] as const;
type TabKey = (typeof TABS)[number];
// The state chip's tone by the state's category (D-155: what needs attention stands out).
const STATE_TONES: Record<AssetState['category'], Tone> = {
  in_stock: 'info',
  in_use: 'success',
  in_repair: 'warning',
  retired: 'default',
  disposed: 'default',
};
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
  const dates = useDateTime();
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
  const [dialog, setDialog] = useState<'move' | 'copy' | 'dispose'>();
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
  const custom = useCustomFields('asset');
  // Age (REQ-AST-011) from the tenant's basis, recalculated live when an admin changes it.
  const settings = useAssetSettings();
  const ageListFormat = useListFormat();
  const basis = settings.data === undefined ? null : basisDay(settings.data.age_basis, asset);
  const age = basis === null ? null : ageBetween(basis, dayjs().format('YYYY-MM-DD'));
  const ageText =
    age === null
      ? t('assets.age.unknown')
      : age.years === 0 && age.months === 0 && age.days === 0
        ? t('assets.age.today')
        : age.years === 0 && age.months === 0
          ? t('assets.age.days', { count: age.days })
          : ageListFormat(
              [
                age.years > 0 ? t('assets.age.years', { count: age.years }) : null,
                age.months > 0 ? t('assets.age.months', { count: age.months }) : null,
                age.days > 0 ? t('assets.age.days', { count: age.days }) : null,
              ].filter((part): part is string => part !== null),
            );
  const customFields = (custom.data ?? [])
    .filter((f) => !f.removed)
    .sort((a, b) => a.sort_order - b.sort_order);
  // Dispose (REQ-AST-017) only where the life cycle has a way into a disposed state from here.
  const moves = useAssetMoves(manage ? asset.id : undefined);
  const disposedIds = new Set(
    (states.data ?? []).filter((x) => x.category === 'disposed').map((x) => x.id),
  );
  const canDispose =
    manage && (moves.data ?? []).some((m) => m.allowed && disposedIds.has(m.to_state_id));
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
  const startEditing = () => {
    if (editing !== undefined) return;
    setEditing({ draft: draftOf(asset), base: asset.version });
    setChangedElsewhere(false);
    // The form is on the Details tab: show it wherever the edit started.
    if (tab !== 'details') setParams({ tab: 'details' }, { replace: true });
  };
  const typeName = type === undefined ? '' : nameOf(type.names, locale);
  // D-155 template A: only the fields that hold a value, then "Add details (n)". A value opens
  // the edit form on a click; people who may not edit see the filled ones only.
  const property = (
    key: string,
    label: string,
    value: ReactNode,
    filled: boolean,
  ): PropertyItem => ({
    key,
    label,
    filled,
    content: manage ? (
      <EditableValue label={label} onEdit={startEditing} empty={!filled}>
        {value}
      </EditableValue>
    ) : (
      value
    ),
  });
  const shown = (items: PropertyItem[]) =>
    manage ? items : items.filter((i) => i.filled || i.always === true);
  const properties = shown([
    property(
      'type',
      t('assets.admin.product_type'),
      <bdi dir="auto">{typeName}</bdi>,
      typeName !== '',
    ),
    property(
      'serial',
      t('assets.record.serial_number'),
      <bdi dir="ltr">{asset.serial_number}</bdi>,
      asset.serial_number !== null,
    ),
    property(
      'barcode',
      t('assets.record.barcode'),
      <bdi dir="ltr">{asset.barcode}</bdi>,
      asset.barcode !== null,
    ),
    property(
      'location',
      t('assets.record.location'),
      <bdi dir="auto">{asset.location}</bdi>,
      asset.location !== null,
    ),
    property(
      'acquired',
      t('assets.record.acquired_on'),
      dates.formatDay(asset.acquired_on),
      asset.acquired_on !== null,
    ),
    property(
      'warranty',
      t('assets.record.warranty_expires_on'),
      dates.formatDay(asset.warranty_expires_on),
      asset.warranty_expires_on !== null,
    ),
    // The age always shows: "Unknown" says the basis date is missing (REQ-AST-011).
    {
      key: 'age',
      label: t('assets.age.label'),
      content: <span data-testid="asset-age">{ageText}</span>,
      filled: true,
      always: true,
    },
    ...customFields.map((field) =>
      property(
        `custom-${field.key}`,
        fieldName(field, locale),
        <CustomFieldValue field={field} value={asset.custom[field.key]} />,
        asset.custom[field.key] != null,
      ),
    ),
  ]);
  const purchase = shown([
    property(
      'price',
      t('assets.record.purchase_price'),
      money(asset.purchase_price),
      asset.purchase_price !== null,
    ),
    property(
      'tax',
      t('assets.record.purchase_tax'),
      money(asset.purchase_tax),
      asset.purchase_tax !== null,
    ),
    {
      key: 'total',
      label: t('assets.admin.total'),
      content: <span data-testid="asset-total">{money(asset.purchase_total)}</span>,
      filled: asset.purchase_total !== null,
    },
  ]);
  const panelSections: PanelSection[] = [
    {
      key: 'properties',
      title: t('assets.record.properties'),
      children: <PropertyList items={properties} testId="asset-props" />,
    },
    // Nothing bought yet and nothing to add: no empty Purchase card (D-155).
    ...(purchase.length > 0
      ? [
          {
            key: 'purchase',
            title: t('assets.record.purchase'),
            children: <PropertyList items={purchase} testId="asset-purchase" />,
          },
        ]
      : []),
  ];
  // The record's actions on one row (D-155): the state change first, then edit and copy; the
  // destructive ones in "More actions", the delete confirmed.
  const actions: RecordAction[] = manage
    ? [
        {
          key: 'move',
          label: t('assets.move.open'),
          allowed: true,
          primary: true,
          rank: 1,
          icon: <SwapOutlined aria-hidden />,
          onClick: () => {
            setDialog('move');
          },
          testId: 'asset-move-open',
        },
        {
          key: 'edit',
          label: t('actions.edit'),
          allowed: editing === undefined,
          whyNot: t('assets.record.editing_now'),
          primary: true,
          rank: 2,
          icon: <EditOutlined aria-hidden />,
          onClick: startEditing,
          testId: 'asset-edit',
        },
        {
          key: 'copy',
          label: t('assets.copy.open'),
          allowed: true,
          primary: true,
          rank: 3,
          icon: <CopyOutlined aria-hidden />,
          onClick: () => {
            setDialog('copy');
          },
          testId: 'asset-copy-open',
        },
        // Dispose (REQ-AST-017) only where the life cycle has a way into a disposed state
        // from here; it asks for its record in its own dialog.
        ...(canDispose
          ? [
              {
                key: 'dispose',
                label: t('assets.dispose.open'),
                allowed: true,
                danger: true,
                onClick: () => {
                  setDialog('dispose');
                },
                testId: 'asset-dispose-open',
              },
            ]
          : []),
        {
          key: 'trash',
          label: t('actions.delete'),
          allowed: true,
          danger: true,
          confirm: t('assets.record.trash_confirm'),
          confirmOk: t('actions.delete'),
          onClick: () => {
            change.mutate(
              { kind: 'delete', id: asset.id, version: asset.version },
              {
                onSuccess: () => void navigate('/assets'),
                onError: reportError,
              },
            );
          },
          testId: 'asset-trash',
        },
      ]
    : [];
  const details = editing ? (
    <Flex vertical gap={12} data-testid="asset-edit-form">
      {changedElsewhere && (
        <Alert
          type="warning"
          showIcon
          message={t('assets.record.changed_elsewhere')}
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
    </Flex>
  ) : (
    <section aria-label={t('assets.record.description')}>
      {asset.description === null || asset.description === '' ? (
        <EmptyText>{t('assets.record.no_description')}</EmptyText>
      ) : (
        <Typography.Paragraph
          style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}
          data-testid="asset-description"
        >
          <bdi dir="auto">{asset.description}</bdi>
        </Typography.Paragraph>
      )}
    </section>
  );
  // Lane C's #344 review: type and location are in the panel, so the facts line keeps only
  // what the panel does not show.
  const facts: ReactNode[] = [
    <span key="created">
      {t('incidents.created_on', { date: dates.format(asset.created_at) })}
    </span>,
  ];
  return (
    <RecordPage
      testId="asset-page"
      header={
        <RecordHeader
          icon={<LaptopOutlined />}
          kind="asset"
          typeLabel={t('assets.record.record_type')}
          displayId={asset.tag ?? t('assets.record.no_tag')}
          // Only a real tag is copied; "No tag" is plain text (lane C's #344 review, #345).
          copyable={asset.tag !== null}
          title={asset.name}
          testIds={{ id: 'asset-display-tag', title: 'asset-heading' }}
          tags={
            <>
              {state !== undefined && (
                <ToneTag tone={STATE_TONES[state.category]} testId="asset-state">
                  {nameOf(state.names, locale)}
                </ToneTag>
              )}
              {asset.loanable && (
                <ToneTag tone="purple" testId="asset-loanable">
                  {t('assets.record.loanable')}
                </ToneTag>
              )}
            </>
          }
          meta={facts}
          extra={<PresenceAvatars viewers={viewers} selfUserId={me ?? null} />}
        />
      }
      actions={
        actions.length > 0 ? (
          <ActionBar actions={actions} max={3} testId="asset-actions" />
        ) : undefined
      }
      panel={<PropertiesPanel testId="asset-panel" sections={panelSections} />}
    >
      <MoveAssetDialog
        asset={asset}
        open={dialog === 'move'}
        onClose={() => {
          setDialog(undefined);
        }}
      />
      <DisposeAssetDialog
        asset={asset}
        open={dialog === 'dispose'}
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
          {
            key: 'details',
            label: t('assets.record.details'),
            children: (
              <Flex vertical gap={16} style={{ paddingBottom: 16 }}>
                {details}
                {state?.category === 'disposed' && (
                  <DisposalCard asset={asset} canManage={manage} />
                )}
              </Flex>
            ),
          },
          {
            key: 'relations',
            label: t('assets.record.relations'),
            children: <AssetRelations asset={asset} manage={manage} />,
          },
          {
            key: 'history',
            label: t('assets.record.history'),
            children: <AssetHistory id={asset.id} />,
          },
        ]}
        data-testid="asset-tabs"
      />
    </RecordPage>
  );
}

function AssetHistory({ id }: { id: string }) {
  const t = useLabel();
  const dates = useDateTime();
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
                {dates.format(entry.occurred_at)}
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
