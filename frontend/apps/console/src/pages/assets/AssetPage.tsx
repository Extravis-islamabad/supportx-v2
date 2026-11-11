import { CopyOutlined, EditOutlined, LaptopOutlined, SwapOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Flex,
  Form,
  Input,
  Modal,
  Segmented,
  Select,
  Skeleton,
  Tabs,
  Timeline,
  Typography,
} from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useState, type ReactNode } from 'react';
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router';

import {
  ApiError,
  queryKeys,
  useAssetFinancials,
  useAssetAccess,
  useAssetHistory,
  useAssetProductTypes,
  useAssetLinked,
  useAssetRecord,
  useAssetMoves,
  useAssetSettings,
  useCustomFields,
  useAssetRecordChange,
  useAssetStates,
  useSession,
  type AssetHistoryFilters,
  type AssetHistorySource,
  type AssetRecord,
  type AssetState,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { useRecordChannel } from '@supportx/realtime';
import {
  ActionBar,
  EditableValue,
  EmptyText,
  FilterBar,
  FiltersDrawer,
  lengthLimit,
  NoAccess,
  PresenceAvatars,
  PropertiesPanel,
  pickerFormat,
  PropertyList,
  RecordHeader,
  RecordPage,
  reportError,
  ToneTag,
  useAccess,
  useAppearance,
  useDateTime,
  useLabel,
  useMinWidth,
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
import { UserPicker } from '../incidents/pickers';
import { CopyAssetDialog, MoveAssetDialog } from './AssetActions';
import { AssetRelations } from './AssetRelations';
import { AssetBookings } from './Bookings';
import { ageBetween, basisDay } from './age';
import { okFooter } from './dialogOk';
import { DisposalCard, DisposeAssetDialog } from './Disposal';
import { AssetFields } from './AssetForm';
import { AssetFinancialsTab } from './Financials';
import { totalShown, useMoney } from './money';
import { AssetNotes } from './Notes';
import { LabelHistory, PrintLabelsDialog } from './PrintLabels';
import { LinkedRecordsPanel } from './LinkedRecords';
import { RaiseFromAssetDialog } from './RaiseFromAsset';
import type { RaiseKind } from './raise';
import { ScansTab } from './Scans';
import { bodyOf, draftOf, type AssetDraft } from './draft';
import { useAssetSaveProblems } from './problems';

// The record's tabs, always in this order (REQ-AST-001 AC3, REQ-AST-048): later sessions add
// theirs here (hardware, software and scan history with discovery; contracts with WP-054).
// Financials only for people who may see money (assets.view_financials).
const TABS = [
  'details',
  'relations',
  'bookings',
  'financials',
  'notes',
  'scans',
  'labels',
  'history',
] as const;
type TabKey = (typeof TABS)[number];
// The state chip's tone by the state's category (D-155: what needs attention stands out).
const STATE_TONES: Record<AssetState['category'], Tone> = {
  in_stock: 'info',
  in_use: 'success',
  in_repair: 'warning',
  retired: 'default',
  disposed: 'default',
};
// REQ-AST-049: what the history can be narrowed to (each a field the asset's history records).
const FILTER_FIELDS = [
  'name',
  'state_id',
  'owner_user_id',
  'site_id',
  'location',
  'product_id',
  'purchase_price',
  'cost_centre',
  'depreciation_method',
  'cost',
  'note',
] as const;
// D-157: money, read only with assets.view_financials (the API masks these lines for others).
const MONEY_FIELDS: ReadonlySet<string> = new Set([
  'purchase_price',
  'purchase_tax',
  'depreciation_method',
  'useful_life_years',
  'salvage_value',
]);
const SOURCES: AssetHistorySource[] = [
  'ui',
  'api',
  'rule',
  'workflow',
  'import',
  'integration',
  'system',
];
const HISTORY_FIELDS = new Set([
  'name',
  'owner_user_id',
  'department_id',
  'parent_asset_id',
  'loanable',
  'relationship',
  'cost_centre',
  'gl_code',
  'depreciation_method',
  'useful_life_years',
  'salvage_value',
  'cost',
  'note',
  'scan',
  'raised_work_item',
  // WP-049b S4b (REQ-AST-052): a merge's lines on both assets.
  'merged_into',
  'merged_from',
  'restored_after_merge',
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
  // A merged asset's ID opens the asset it went into (REQ-AST-052 AC2).
  const survivor =
    asset.error instanceof ApiError && asset.error.code === 'asset_merged'
      ? asset.error.params.survivor_id
      : undefined;
  if (typeof survivor === 'string' && survivor !== '' && survivor !== id) {
    return <Navigate to={`/assets/${survivor}`} replace />;
  }
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
  // Money (REQ-AST-036..038) only for people with assets.view_financials: no tab, no figures.
  const seesMoney = access.can('assets.view_financials');
  const asked = params.get('tab') as TabKey;
  const tab: TabKey =
    TABS.includes(asked) && (asked !== 'financials' || seesMoney) ? asked : 'details';
  const types = useAssetProductTypes();
  const states = useAssetStates();
  const change = useAssetRecordChange();
  const { problems, show, clear } = useAssetSaveProblems();
  const [editing, setEditing] = useState<{ draft: AssetDraft; base: number }>();
  const [changedElsewhere, setChangedElsewhere] = useState(false);
  const [dialog, setDialog] = useState<'move' | 'copy' | 'dispose'>();
  const [printing, setPrinting] = useState(false);
  // WP-049b s4a: the linked work items (REQ-AST-044) and raising one from here (045).
  const linked = useAssetLinked(asset.id);
  const [raising, setRaising] = useState<RaiseKind>();
  const viewers = useRecordChannel('asset', asset.id, (event) => {
    // The asset's files (REQ-AST-050), its notes and cost lines (parts, no version of the asset).
    if (event.type === 'files.changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.files.record('asset', asset.id) });
      return;
    }
    const parts = event.fields ?? [];
    // WP-049b s3: a scan arrived (REQ-AST-054); a fix from an audit changed the asset itself.
    if (parts.includes('scans')) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.scans(asset.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.history(asset.id) });
      return;
    }
    // WP-049b s4a: a work item linked, unlinked or moved on (REQ-AST-044): the counters.
    if (parts.includes('linked')) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.linked(asset.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.history(asset.id) });
      return;
    }
    if (parts.includes('notes') || parts.includes('costs')) {
      if (parts.includes('notes')) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.assets.notes(asset.id) });
      }
      if (parts.includes('costs')) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.assets.financials(asset.id) });
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.history(asset.id) });
      return;
    }
    if (event.version !== undefined && event.version <= asset.version) return; // our own save
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.history(asset.id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.financials(asset.id) });
    if (editing === undefined) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.record(asset.id) });
    } else {
      setChangedElsewhere(true);
    }
  });
  const manage = access.can('assets.manage');
  // D-157: without assets.manage, a technician may still change this asset's state, location,
  // notes and fitted parts while it is linked to their own ticket and held by its requester.
  const reach = useAssetAccess(manage ? undefined : asset.id);
  const throughTicket = !manage && reach.data?.through_ticket === true;
  const [locating, setLocating] = useState<string>();
  // Two buttons on a phone, as on a request: a third wrapped "More actions" to a second line
  // (the visual matrix at 390 px, once the showcase had an asset to show).
  const wide = useMinWidth(576);
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
  const moves = useAssetMoves(manage || throughTicket ? asset.id : undefined);
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
  const ledgerAccount = asset.gl_code;
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
      'cost-centre',
      t('assets.record.cost_centre'),
      <bdi dir="auto">{asset.cost_centre}</bdi>,
      asset.cost_centre !== null,
    ),
    property(
      'gl-code',
      t('assets.record.gl_code'),
      // A GL code is typed by a person (free text, REQ-AST-038), not a code of ours.
      <bdi dir="ltr">{ledgerAccount}</bdi>,
      asset.gl_code !== null,
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
  // The side panel's value (REQ-AST-048): book value and total cost, for those who see money.
  const figures = useAssetFinancials(asset.id, seesMoney);
  const inBase = useMoney(figures.data?.currency);
  const value: PropertyItem[] =
    figures.data === undefined
      ? []
      : [
          {
            key: 'book-value',
            label: t('assets.financials.book_value'),
            content: (
              <span data-testid="asset-panel-book-value">
                {inBase(figures.data.book_value) ?? t('assets.financials.not_known')}
              </span>
            ),
            filled: true,
          },
          {
            key: 'tco',
            label: t('assets.financials.total_cost'),
            content: (
              <span data-testid="asset-panel-total-cost">{totalShown(inBase, figures.data)}</span>
            ),
            filled: true,
          },
        ];
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
    ...(value.length > 0
      ? [
          {
            key: 'value',
            title: t('assets.financials.value'),
            children: <PropertyList items={value} testId="asset-value" />,
          },
        ]
      : []),
    // Hidden until work items offer the links (lane A's port; the API says "not available").
    ...(linked.data?.available === true
      ? [
          {
            key: 'linked',
            title: t('assets.linked.title'),
            children: <LinkedRecordsPanel assetId={asset.id} summary={linked.data} />,
            testId: 'asset-linked-section',
          },
        ]
      : []),
  ];
  // Raise a work item from the asset (REQ-AST-045): only the kinds the person may create.
  const raiseActions: RecordAction[] = (
    [
      ['incident', 'incidents.create'],
      ['service_request', 'requests.create'],
      ['change', 'changes.create'],
    ] as const
  )
    .filter(([, permission]) => access.can(permission))
    .map(([kind]) => ({
      key: `raise-${kind}`,
      label: t(`assets.raise.${kind}`),
      allowed: true,
      onClick: () => {
        setRaising(kind);
      },
      testId: `asset-raise-${kind}`,
    }));
  // The record's actions on one row (D-155): the state change first, then edit and copy; the
  // destructive ones in "More actions", the delete confirmed.
  const ticketActions: RecordAction[] = [
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
      key: 'location',
      label: t('assets.record.change_location'),
      allowed: true,
      primary: true,
      rank: 2,
      icon: <EditOutlined aria-hidden />,
      onClick: () => {
        setLocating(asset.location ?? '');
      },
      testId: 'asset-location-open',
    },
  ];
  // Labels (REQ-AST-039) for everyone who may see the asset: its QR code or barcode.
  const labelAction: RecordAction = {
    key: 'labels',
    label: t('assets.labels.print_action'),
    allowed: true,
    // A button for those who only view (their one action); in "More actions" for managers and
    // for a technician working through its ticket (D-157), whose own actions come first.
    primary: !manage && !throughTicket,
    rank: 4,
    onClick: () => {
      setPrinting(true);
    },
    testId: 'asset-labels-open',
  };
  // A technician through a ticket sees its ticket actions first (D-157); raising a work item
  // from the asset (REQ-AST-045) follows, in "More actions".
  const actions: RecordAction[] = !manage
    ? throughTicket
      ? [...ticketActions, labelAction, ...raiseActions]
      : [labelAction, ...raiseActions]
    : [
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
        labelAction,
        ...raiseActions,
      ];
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
          <ActionBar actions={actions} max={wide ? 3 : 2} testId="asset-actions" />
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
      {raising !== undefined && (
        <RaiseFromAssetDialog
          asset={asset}
          kind={raising}
          onClose={() => {
            setRaising(undefined);
          }}
        />
      )}
      {/* D-157: the location alone, for a technician through its ticket. */}
      <Modal
        open={locating !== undefined}
        title={t('assets.record.change_location')}
        cancelText={t('actions.cancel')}
        onCancel={() => {
          setLocating(undefined);
          clear();
        }}
        footer={okFooter({
          okText: t('actions.save'),
          loading: change.isPending,
          onOk: () => {
            clear();
            const location = (locating ?? '').trim();
            change.mutate(
              {
                kind: 'update',
                id: asset.id,
                version: asset.version,
                body: { location: location === '' ? null : location },
              },
              {
                onSuccess: () => {
                  setLocating(undefined);
                },
                onError: show,
              },
            );
          },
          testId: 'asset-location-save',
        })}
        destroyOnHidden
      >
        <Form layout="vertical" component="div">
          <Problems problems={problems} testId="asset-location-problems" />
          <Form.Item label={t('assets.record.location')} htmlFor="asset-location-only">
            <Input
              id="asset-location-only"
              dir="auto"
              count={lengthLimit(200)}
              value={locating}
              onChange={(event) => {
                setLocating(event.target.value);
              }}
              data-testid="asset-location-only"
            />
          </Form.Item>
        </Form>
      </Modal>
      {printing && (
        <PrintLabelsDialog
          assetIds={[asset.id]}
          open={printing}
          onClose={() => {
            setPrinting(false);
          }}
        />
      )}
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
                {throughTicket && (
                  <Alert
                    type="info"
                    showIcon
                    message={t('assets.record.through_ticket')}
                    data-testid="asset-through-ticket"
                  />
                )}
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
            children: (
              <AssetRelations asset={asset} manage={manage} parts={manage || throughTicket} />
            ),
          },
          {
            // WP-049b s1 (REQ-AST-032): bookings ahead, handed over as loans.
            key: 'bookings',
            label: t('assets.bookings.title'),
            children: <AssetBookings asset={asset} manage={manage} />,
          },
          // WP-049b s2 (REQ-AST-036..038): money, for those who may see it.
          ...(seesMoney
            ? [
                {
                  key: 'financials',
                  label: t('assets.financials.title'),
                  children: <AssetFinancialsTab asset={asset} manage={manage} />,
                },
              ]
            : []),
          {
            // WP-049b s2 (REQ-AST-050): notes and attachments.
            key: 'notes',
            label: t('assets.notes.tab'),
            children: <AssetNotes asset={asset} manage={manage} />,
          },
          {
            // WP-049b s3 (REQ-AST-054): scan history, kept as the asset settings say.
            key: 'scans',
            label: t('assets.scans.tab'),
            children: <ScansTab assetId={asset.id} />,
          },
          {
            // WP-049b s3 (REQ-AST-039 AC3): every print and reprint of its label.
            key: 'labels',
            label: t('assets.labels.tab'),
            children: <LabelHistory assetId={asset.id} />,
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

/**
 * The asset's history (REQ-AST-049): every change newest first, with sub-views for state and
 * assignment (owner changes and loans), and filters by field, source, person and days. Live:
 * any change of the asset refetches it.
 */
function AssetHistory({ id }: { id: string }) {
  const t = useLabel();
  const dates = useDateTime();
  const { dates: formats } = useAppearance();
  const [filters, setFilters] = useState<AssetHistoryFilters>({});
  const [filtersOpen, setFiltersOpen] = useState(false);
  const history = useAssetHistory(id, filters);
  const seesMoney = useAccess().can('assets.view_financials');
  const list = useListFormat();
  const entries = history.data?.pages.flatMap((p) => p.items) ?? [];
  // Field codes never show (§5d): each known one by its label, a custom field as such.
  const field = (name: string) =>
    name.startsWith('custom.')
      ? t('assets.record.custom_field')
      : HISTORY_FIELDS.has(name)
        ? t(`assets.record.${name}`)
        : t('assets.record.other_field');
  // REQ-AST-045: "INC-42 raised from this asset" (the record's ID when the event named it).
  const line = (change: { field: string; new?: unknown }) => {
    if (change.field !== 'raised_work_item') return field(change.field);
    const raised = (change.new ?? {}) as { display_id?: string | null };
    return raised.display_id != null && raised.display_id !== ''
      ? t('assets.record.raised_from', { display_id: raised.display_id })
      : t('assets.record.raised_from_unnamed');
  };
  const set = (patch: Partial<AssetHistoryFilters>) => {
    setFilters({ ...filters, ...patch });
  };
  const filtered = Object.values(filters).some((v) => v !== undefined && v !== 'all');
  // The bar holds the sub-view; the rest sit in the drawer, so a phone keeps one row (D-124).
  const drawerCount = [
    filters.field,
    filters.source,
    filters.actorId,
    filters.since ?? filters.until,
  ].filter((v) => v !== undefined).length;
  const range: [Dayjs | null, Dayjs | null] | null =
    filters.since === undefined && filters.until === undefined
      ? null
      : [
          filters.since === undefined ? null : dayjs(filters.since),
          filters.until === undefined ? null : dayjs(filters.until),
        ];
  return (
    <Card>
      <div style={{ marginBottom: 16 }}>
        <FilterBar
          testId="asset-history-filters"
          view={
            <Segmented<NonNullable<AssetHistoryFilters['view']>>
              value={filters.view ?? 'all'}
              onChange={(view) => {
                set({ view: view === 'all' ? undefined : view });
              }}
              options={(['all', 'state', 'assignment'] as const).map((v) => ({
                value: v,
                label: t(`assets.history.view_${v}`),
              }))}
              data-testid="asset-history-view"
            />
          }
          filtersCount={drawerCount}
          onOpenFilters={() => {
            setFiltersOpen(true);
          }}
          extra={
            filtered ? (
              <Button
                type="link"
                onClick={() => {
                  setFilters({});
                }}
                data-testid="asset-history-clear"
              >
                {t('assets.history.clear')}
              </Button>
            ) : undefined
          }
        />
      </div>
      <FiltersDrawer
        open={filtersOpen}
        onClose={() => {
          setFiltersOpen(false);
        }}
        onReset={() => {
          // The drawer's own filters; the sub-view in the bar stays.
          setFilters(filters.view === undefined ? {} : { view: filters.view });
        }}
        testId="asset-history-drawer"
      >
        <Form layout="vertical" component="div">
          <Form.Item label={t('assets.history.field')} htmlFor="asset-history-field">
            <Select<string>
              id="asset-history-field"
              allowClear
              aria-label={t('assets.history.field')}
              value={filters.field}
              onChange={(value: string | undefined) => {
                set({ field: value });
              }}
              options={FILTER_FIELDS.filter((f) => seesMoney || !MONEY_FIELDS.has(f)).map((f) => ({
                value: f,
                label: field(f),
              }))}
              data-testid="asset-history-field"
            />
          </Form.Item>
          <Form.Item label={t('assets.history.source')} htmlFor="asset-history-source">
            <Select<AssetHistorySource>
              id="asset-history-source"
              allowClear
              aria-label={t('assets.history.source')}
              value={filters.source}
              onChange={(value: AssetHistorySource | undefined) => {
                set({ source: value });
              }}
              options={SOURCES.map((s) => ({ value: s, label: t(`change_source.${s}`) }))}
              data-testid="asset-history-source"
            />
          </Form.Item>
          <Form.Item label={t('assets.history.person')} htmlFor="asset-history-person">
            <UserPicker
              id="asset-history-person"
              value={filters.actorId ?? null}
              onChange={(person) => {
                set({ actorId: person ?? undefined });
              }}
              testId="asset-history-person"
              ariaLabel={t('assets.history.person')}
            />
          </Form.Item>
          <Form.Item label={t('assets.history.days')} htmlFor="asset-history-days">
            <DatePicker.RangePicker
              id={{ start: 'asset-history-days' }}
              allowEmpty={[true, true]}
              aria-label={t('assets.history.days')}
              format={pickerFormat(formats, false)}
              value={range}
              onChange={(days) => {
                set({
                  since: days?.[0]?.format('YYYY-MM-DD') ?? undefined,
                  until: days?.[1]?.format('YYYY-MM-DD') ?? undefined,
                });
              }}
              style={{ width: '100%' }}
              data-testid="asset-history-days"
            />
          </Form.Item>
        </Form>
      </FiltersDrawer>
      {entries.length === 0 && !history.isPending && (
        <EmptyText>{t(filtered ? 'assets.history.none_match' : 'assets.history.none')}</EmptyText>
      )}
      <Timeline
        items={entries.map((entry) => ({
          key: `${String(entry.version)}-${entry.occurred_at}`,
          children: (
            <Flex vertical gap={2} data-testid={`asset-history-${String(entry.version)}`}>
              <Typography.Text type="secondary">
                {dates.format(entry.occurred_at)}
                {' · '}
                <bdi dir="auto">{entry.actor_name ?? t('assets.record.someone')}</bdi>
                {' · '}
                {t(`change_source.${entry.source}`)}
              </Typography.Text>
              <span>
                {entry.kind === 'created'
                  ? t('assets.record.history_created')
                  : list([...new Set(entry.changes.map((c) => line(c)))])}
              </span>
              {/* What made it (WP-049b s3): an audit's fix names the audit; or the rule. */}
              {entry.origin != null && (
                <Typography.Text type="secondary" data-testid="asset-history-origin">
                  <bdi dir="auto">
                    {entry.origin.reason_code != null
                      ? t(`asset_change_reason.${entry.origin.reason_code}`, {
                          ...entry.origin.reason_params,
                        })
                      : t(`asset_change_origin.${entry.origin.kind}`, {
                          display_id: entry.origin.display_id ?? '',
                          name: entry.origin.name ?? '',
                        })}
                  </bdi>
                </Typography.Text>
              )}
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
