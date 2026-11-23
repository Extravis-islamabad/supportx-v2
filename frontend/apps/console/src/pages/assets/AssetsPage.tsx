import { useQueryClient } from '@tanstack/react-query';
import { ApartmentOutlined } from '@ant-design/icons';
import { App, Button, Flex, Grid, Input, Select, Table, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

import {
  ApiError,
  ASSET_BULK_MAX,
  queryKeys,
  useAssetProductTypes,
  useAssetGroups,
  useAssetRecordChange,
  useAssetRelations,
  useAssetRecords,
  useAssetStates,
  useAssetTypeCounts,
  useLoanActions,
  useRestoreAsset,
  useStructure,
  sharedListKeys,
  listSettingKey,
  type AssetRecord,
  type FilterExpression,
} from '@supportx/api-client';
import {
  refreshList,
  useListChannel,
  usePersonalChannel,
  useTenantChannel,
} from '@supportx/realtime';
import {
  CellText,
  Drawer,
  EmptyText,
  FilterBar,
  HeaderActions,
  ListNotice,
  ListPage,
  NoAccess,
  PageHeader,
  reportError,
  ToneTag,
  useAccess,
  useAppearance,
  useColumnWidths,
  useLabel,
  useLicence,
  WriteButton,
  type MoreAction,
} from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { Problems } from '../admin/incidents/shared';
import { nameOf } from '../admin/assets/shared';
import { typeTree, type TypeNode } from '../admin/assets/tree';
import { AssetViewPicker, AssetViewsDrawer } from './AssetViews';
import { TypeTree } from './TypeTree';
import { ALL_TYPES } from './typeCounts';
import { isBuiltIn, TRASH, useAssetViewChoices } from './views';
import { useSiteNames } from './live';
import { AssetListExport } from './AssetExport';
import { BulkActionsDialog, MergeDialog } from './BatchActions';
import { ImportWizard } from './ImportWizard';
import { PrintLabelsButton } from './PrintLabels';
import { AssetFields } from './AssetForm';
import { bodyOf, draftOf, type AssetDraft } from './draft';
import { useAssetSaveProblems } from './problems';
import { SelectPageBox } from '../incidents/list/ColumnChooser';
import { MyExportsButton } from '../reports/exports';

/**
 * The asset list (WP-049a s2; WP-049b s4a, REQ-AST-047): the product type tree beside the list
 * (a node lists its types and every type below, with counts), built-in views, your saved views
 * and favourites, search by name or any identifier, the trash. The default columns are the
 * spec's; each person's widths are kept per view (the shared list-settings store). It follows
 * the asset list channel live (and the catalogue broadcast for names), so another person's
 * change shows without a refresh.
 *
 * WP-049b S4b: up to 1,000 picked rows go to a bulk job (edit, change state, assign, trash;
 * REQ-AST-051), two to the merge dialog (052); the header imports a file and exports the list
 * as it is shown (053). A merged asset in the trash asks before it is restored.
 */
// WP-049b S4b: a bulk job takes up to 1,000 assets (REQ-AST-051); the server says so too.
const BULK_MAX = ASSET_BULK_MAX;
const LIST_SETTINGS_CHANGED = 'system.list_settings_changed';
// Every column starts at a width of its own (QA 2026-11-12 V-03): the table then knows how wide
// it is, scrolls sideways inside its box, and the columns pinned at its sides stay put.
const OWN_WIDTHS: Record<string, number> = {
  tag: 130,
  name: 220,
  user: 160,
  department: 170,
  parent: 130,
  product: 190,
  type: 150,
  site: 180,
  serial: 150,
  state: 140,
};
const SELECT_WIDTH = 48;
const RESTORE_WIDTH = 120;

/** Every product type ID in the branch (the node and below), for a saved view's filter. */
function branchIds(nodes: TypeNode[], id: string): string[] {
  for (const node of nodes) {
    if (node.id === id) {
      const all: string[] = [];
      const walk = (n: TypeNode) => {
        all.push(n.id);
        (n.children ?? []).forEach(walk);
      };
      walk(node);
      return all;
    }
    const inner = branchIds(node.children ?? [], id);
    if (inner.length > 0) return inner;
  }
  return [];
}

export function AssetsPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const access = useAccess();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const allowed = access.can('assets.view');
  const screens = Grid.useBreakpoint();
  const { writable } = useLicence();
  // On a phone the type tree waits behind a button (QA 2026-11-12 V-03: its 20 rows came before
  // any asset); from md up it sits beside the list.
  const narrow = screens.md !== true;
  const [treeOpen, setTreeOpen] = useState(false);
  const [myExportsOpen, setMyExportsOpen] = useState(false);
  const [search, setSearch] = useState('');
  // The view and the tree node live in the address, so a view can be shared as a link.
  const [params, setParams] = useSearchParams();
  const view = params.get('view') ?? 'all';
  const typeId = params.get('type') ?? undefined;
  const setParam = (name: 'view' | 'type', value: string | undefined) => {
    const next = new URLSearchParams(params);
    if (value === undefined || value === '' || (name === 'view' && value === 'all')) {
      next.delete(name);
    } else next.set(name, value);
    setParams(next, { replace: true });
  };
  const trash = view === TRASH;
  const { choices, saved } = useAssetViewChoices(allowed);
  const savedView = saved(view);
  const [viewsOpen, setViewsOpen] = useState(false);
  const debounced = useDebounced(search, 300);
  const list = useAssetRecords(
    {
      search: debounced,
      productTypeId: typeId,
      trash,
      view: isBuiltIn(view) && view !== 'all' ? view : undefined,
      filter: savedView?.filter == null ? undefined : JSON.stringify(savedView.filter),
    },
    allowed,
  );
  const counts = useAssetTypeCounts(isBuiltIn(view) ? view : undefined, allowed && !trash);
  const ownCounts = useMemo(
    () => new Map((counts.data?.types ?? []).map((c) => [c.product_type_id, c.count])),
    [counts.data],
  );
  const departments = useStructure('departments', allowed, true);
  const siteName = useSiteNames();
  const types = useAssetProductTypes(allowed);
  const states = useAssetStates(allowed);
  const change = useAssetRecordChange();
  const { problems, show, clear } = useAssetSaveProblems();
  const [adding, setAdding] = useState<{ draft: AssetDraft; key: string }>();
  useListChannel(allowed ? 'assets' : null, () => {
    refreshList(queryClient, [...queryKeys.assets.all, 'records']);
  });
  // Your views and widths changed in another window of yours (rule 5c): follow them.
  usePersonalChannel((message) => {
    if (message.type !== LIST_SETTINGS_CHANGED || !message.ids.includes('assets')) return;
    void queryClient.invalidateQueries({ queryKey: sharedListKeys.all('assets') });
    if (message.ids.includes(view)) {
      void queryClient.invalidateQueries({ queryKey: listSettingKey('assets', view) });
    }
  });
  useTenantChannel((message) => {
    if (message.type === 'assets.catalogue_changed' || message.type === 'refresh') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.all });
    }
  });
  const rows = useMemo(() => list.data?.pages.flatMap((page) => page.items) ?? [], [list.data]);
  // Bulk moves (WP-049a s3): pick rows, move them to one state; the server checks each one.
  const bulkAllowed = !trash && access.can('assets.manage');
  // Labels (WP-049b s3, REQ-AST-039) need only assets.view: anyone who sees the list may pick
  // rows to print; the other bulk actions stay with assets.manage.
  const selectable = !trash;
  const [selected, setSelected] = useState<string[]>([]);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const restore = useRestoreAsset();
  const groups = useAssetGroups(bulkAllowed);
  const staticGroups = groups.data?.filter((g) => g.kind === 'static');
  const { addMembers } = useAssetRelations();
  const { setLoanable } = useLoanActions();
  const { message, modal } = App.useApp();
  const tree = useMemo(() => typeTree(types.data ?? []), [types.data]);
  const titles: Record<string, string> = {
    tag: t('assets.record.tag'),
    name: t('assets.record.name'),
    user: t('assets.list.user'),
    department: t('assets.record.department_id'),
    parent: t('assets.list.parent'),
    product: t('assets.record.product'),
    type: t('assets.admin.product_type'),
    site: t('assets.record.site_id'),
    serial: t('assets.record.serial_number'),
    // Last, pinned at the end side on wide screens: the state stays in sight, and its edge
    // shows that more columns lie under it (the sideways-scroll cue).
    state: t('assets.record.state'),
  };
  // Each person's widths per view, kept for them (the shared store; not in the trash).
  const widths = useColumnWidths({
    kind: 'assets',
    viewKey: view,
    enabled: allowed && !trash,
    keys: Object.keys(titles),
    defaults: OWN_WIDTHS,
    minWidths: { name: 160 },
    label: (key) => t('layout.resize_column', { column: titles[key] ?? '' }),
  });
  // Pinned columns from md up only: on a phone they would take most of the width. Ant Design's
  // table reads `left` as the start side: in Arabic and Urdu it pins them on the right itself.
  const startSide: 'left' | undefined = narrow ? undefined : 'left';
  const endSide: 'right' | undefined = narrow ? undefined : 'right';
  if (!allowed) return <NoAccess titleKey="nav.assets" />;
  const page = list.data?.pages;
  const nameIn = (pick: 'people' | 'parents' | 'products', id: string | null | undefined) =>
    id == null ? '' : (page?.map((p) => p[pick]?.[id]).find((n) => n !== undefined) ?? '');
  const departmentName = (id: string | null | undefined) =>
    id == null
      ? ''
      : (((departments.data ?? []).find((d) => d.id === id) as { name?: string } | undefined)
          ?.name ?? '');
  // The list as filtered now, as the list API's filter: what "save as a view" keeps.
  const currentFilter = (): Record<string, unknown> | null => {
    const parts: Record<string, unknown>[] = [];
    if (typeId !== undefined) {
      parts.push({ field: 'product_type_id', op: 'in', value: branchIds(tree, typeId) });
    }
    const text = debounced.trim();
    if (text !== '') {
      parts.push({
        or: ['name', 'tag', 'serial_number'].map((field) => ({
          field,
          op: 'contains',
          value: text,
        })),
      });
    }
    if (parts.length === 0) return savedView?.filter ?? null;
    return parts.length === 1 ? (parts[0] ?? null) : { and: parts };
  };
  const column = (key: string) => ({
    key,
    title: titles[key],
    width: widths.width(key),
    fixed: key === 'tag' ? startSide : key === 'state' && !trash ? endSide : undefined,
    onHeaderCell: () => widths.header(key),
  });
  // The table's own width: it scrolls inside its box when the box is narrower (never the page).
  const tableWidth =
    (selectable ? SELECT_WIDTH : 0) +
    (trash ? RESTORE_WIDTH : 0) +
    Object.keys(titles).reduce((sum, key) => sum + (widths.width(key) ?? OWN_WIDTHS[key] ?? 0), 0);
  const typeName = (id: string) => {
    const found = types.data?.find((x) => x.id === id);
    return found === undefined ? '' : nameOf(found.names, locale);
  };
  const stateName = (id: string) => {
    const found = states.data?.find((x) => x.id === id);
    return found === undefined ? '' : nameOf(found.names, locale);
  };
  const save = () => {
    if (adding === undefined) return;
    clear();
    change.mutate(
      { kind: 'create', key: adding.key, body: bodyOf(adding.draft) as never },
      {
        onSuccess: (made) => {
          setAdding(undefined);
          if (made !== undefined) void navigate(`/assets/${made.id}`);
        },
        onError: show,
      },
    );
  };
  // Escape or the close button with something typed asks first, like every edit drawer
  // (EditDrawer's "Discard changes?"; QA10-P4-38); an untouched form just closes.
  const closeAdding = () => {
    if (adding === undefined) return;
    if (Object.keys(bodyOf(adding.draft, draftOf(null))).length === 0) {
      setAdding(undefined);
      return;
    }
    modal.confirm({
      title: t('settings.discard_title'),
      content: t('settings.discard_body'),
      okText: t('settings.discard'),
      okButtonProps: { danger: true, 'data-testid': 'asset-add-discard' },
      cancelText: t('settings.keep_editing'),
      onOk: () => {
        setAdding(undefined);
      },
    });
  };
  // A merged asset comes back only after the warning (REQ-AST-052): it returns on its own and
  // what moved to the asset kept stays there.
  const restoreAsset = (id: string) => {
    restore.mutate(
      { id, confirmMerged: false },
      {
        onError: (error) => {
          if (!(error instanceof ApiError) || error.code !== 'asset_restore_merged') {
            reportError(error);
            return;
          }
          const survivor = String(error.params.asset ?? '');
          modal.confirm({
            title: t('assets.merge.restore_title'),
            content: t('assets.merge.restore_body', { asset: survivor }),
            okText: t('assets.merge.restore_ok'),
            okButtonProps: { 'data-testid': 'asset-restore-merged-ok' },
            cancelText: t('actions.cancel'),
            onOk: () => {
              restore.mutate({ id, confirmMerged: true }, { onError: reportError });
            },
          });
        },
      },
    );
  };
  // The list as it is shown, as the export's filter; a built-in view the filter language
  // cannot say (and the trash) is not exported, and the button says why.
  // currentFilter builds the list API's filter DSL, the very shape the export takes.
  const shownFilter = currentFilter() as FilterExpression | null;
  const exportFilter: FilterExpression | null | undefined =
    trash || (isBuiltIn(view) && view !== 'all') ? null : (shownFilter ?? undefined);
  // The server's count when it gives one, else the rows when they are all loaded.
  const total =
    list.data === undefined
      ? undefined
      : (list.data.pages[0]?.estimated_total ?? (list.hasNextPage ? undefined : rows.length));
  // Rows selected: the selection bar takes the toolbar's place (D-155), so the list keeps one
  // control row; it goes once nothing is selected.
  const selectionBar =
    selectable && selected.length > 0 ? (
      <Flex gap={8} wrap align="center" data-testid="assets-selection">
        <Typography.Text strong>
          {t('assets.bulk_move.selected', { count: selected.length })}
        </Typography.Text>
        <PrintLabelsButton assetIds={selected} testId="assets-print-labels" />
        {bulkAllowed && (
          <>
            {/* REQ-AST-051: edit, change state, assign or trash, as a background job. */}
            <WriteButton
              onClick={() => {
                setBulkOpen(true);
              }}
              data-testid="assets-bulk-open"
            >
              {t('assets.bulk.open')}
            </WriteButton>
            {/* REQ-AST-052: two duplicates, merged with a field-by-field choice. */}
            <WriteButton
              disabled={selected.length !== 2}
              whyDisabled={selected.length !== 2 ? t('assets.merge.choose_two') : undefined}
              onClick={() => {
                setMergeOpen(true);
              }}
              data-testid="assets-merge-open"
            >
              {t('assets.merge.open')}
            </WriteButton>
            {/* REQ-AST-028 AC2: a static group is filled from the selection in one step. */}
            <Select
              placeholder={t('assets.groups.add_selected')}
              aria-label={t('assets.groups.add_selected')}
              style={{ minWidth: 200 }}
              value={null}
              options={(staticGroups ?? []).map((g) => ({ value: g.id, label: g.name }))}
              onChange={(groupId: string) => {
                addMembers.mutate(
                  { groupId, assetIds: selected },
                  {
                    onSuccess: (answer) => {
                      void message.success(t('assets.groups.added', { count: answer.added }));
                      setSelected([]);
                    },
                    onError: reportError,
                  },
                );
              }}
              data-testid="assets-add-to-group"
            />
            {/* REQ-AST-029: the selection goes on loans from now on. */}
            <WriteButton
              loading={setLoanable.isPending}
              onClick={() => {
                setLoanable.mutate(
                  { assetIds: selected, loanable: true },
                  {
                    onSuccess: () => {
                      void message.success(t('assets.loanable.done'));
                      setSelected([]);
                    },
                    onError: reportError,
                  },
                );
              }}
              data-testid="assets-make-loanable"
            >
              {t('assets.loanable.make')}
            </WriteButton>
          </>
        )}
        <Button
          type="link"
          onClick={() => {
            setSelected([]);
          }}
          style={{ marginInlineStart: 'auto' }}
          data-testid="assets-selection-clear"
        >
          {t('assets.bulk_move.clear')}
        </Button>
      </Flex>
    ) : undefined;
  const canImport =
    access.can('assets.manage') || access.can('vendors.create') || access.can('vendors.manage');
  const goTo = (key: string, path: string, label: string): MoreAction => ({
    key,
    label,
    onClick: () => void navigate(path),
    testId: `assets-${key}-link`,
  });
  const moreActions: MoreAction[] = [
    ...(canImport
      ? [
          {
            key: 'import',
            label: t('assets.import.open'),
            // A read-only licence keeps the import closed, as WriteButton does elsewhere.
            disabled: !writable,
            onClick: () => {
              setImportOpen(true);
            },
            testId: 'assets-import-open',
          },
        ]
      : []),
    ...(access.can('reports.export')
      ? [
          {
            key: 'my-exports',
            label: t('reports.my_exports'),
            onClick: () => {
              setMyExportsOpen(true);
            },
            testId: 'report-my-exports',
          },
        ]
      : []),
    goTo('vendors', '/assets/vendors', t('assets.record.vendors')),
    goTo('groups', '/assets/groups', t('assets.groups.title')),
    goTo('loans', '/assets/loans', t('assets.loans.title')),
    goTo('consumables', '/assets/consumables', t('assets.stock.title')),
    goTo('audits', '/assets/audits', t('assets.audits.title')),
  ];
  // On a phone: the type tree opens from here, the chosen type named on the button.
  const chosenType = typeId === undefined ? '' : typeName(typeId);
  const treeToggle = !trash && narrow && (
    <Button
      icon={<ApartmentOutlined />}
      aria-expanded={treeOpen}
      aria-controls="asset-tree-panel"
      onClick={() => {
        setTreeOpen(!treeOpen);
      }}
      data-testid="asset-tree-toggle"
    >
      {chosenType === '' ? t('assets.tree.label') : t('assets.tree.chosen', { type: chosenType })}
    </Button>
  );
  return (
    <ListPage
      testId="assets-list"
      header={
        <PageHeader
          title={t('nav.assets')}
          count={total === undefined ? undefined : String(total)}
          testId="assets-header"
          extra={
            // D-147 template C (QA 2026-11-12 V-03): Export and "Add asset" stay in sight; the
            // asset registers, "My exports" and the import wait in "More".
            <HeaderActions
              testId="assets-header-actions"
              buttons={[
                {
                  key: 'export',
                  node: <AssetListExport filter={exportFilter} title={t('nav.assets')} />,
                },
              ]}
              more={moreActions}
              primary={
                access.can('assets.manage') ? (
                  <WriteButton
                    type="primary"
                    onClick={() => {
                      clear();
                      setAdding({ draft: draftOf(null), key: crypto.randomUUID() });
                    }}
                    data-testid="asset-add"
                  >
                    {t('assets.record.add')}
                  </WriteButton>
                ) : undefined
              }
            />
          }
        />
      }
      filters={
        <FilterBar
          testId="assets-filterbar"
          selection={selectionBar}
          view={
            <Flex gap={8} wrap align="center">
              <AssetViewPicker
                value={savedView !== undefined || isBuiltIn(view) || trash ? view : 'all'}
                onChange={(key) => {
                  setSelected([]);
                  setParam('view', key);
                }}
                choices={choices}
                withTrash={access.can('assets.manage')}
              />
              <Button
                onClick={() => {
                  setViewsOpen(true);
                }}
                data-testid="assets-views-open"
              >
                {t('assets.views.manage')}
              </Button>
            </Flex>
          }
          search={
            <Input.Search
              allowClear
              aria-label={t('assets.record.search')}
              placeholder={t('assets.record.search')}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
              }}
              data-testid="assets-search"
            />
          }
          quick={
            treeToggle !== false || widths.changed ? (
              <>
                {treeToggle}
                {widths.changed && (
                  <Button onClick={widths.reset} data-testid="assets-reset-widths">
                    {t('layout.reset_widths')}
                  </Button>
                )}
              </>
            ) : undefined
          }
        />
      }
      alerts={
        trash ? (
          <ListNotice testId="assets-trash-notice">{t('assets.record.trash_notice')}</ListNotice>
        ) : view === 'recently_discovered' ? (
          // Said plainly (the coordinator): discovery does not exist yet, so the view is empty.
          <ListNotice testId="assets-discovered-notice">
            {t('assets.views.discovered_notice')}
          </ListNotice>
        ) : undefined
      }
    >
      <AssetViewsDrawer
        open={viewsOpen}
        onClose={() => {
          setViewsOpen(false);
        }}
        choices={choices}
        current={view}
        filter={currentFilter()}
        onSaved={(key) => {
          setParam('view', key);
        }}
      />
      <Flex gap={16} wrap={!screens.md} align="flex-start">
        {!trash && (!narrow || treeOpen) && (
          <nav
            id="asset-tree-panel"
            aria-label={t('assets.tree.label')}
            style={{
              flex: screens.md ? '0 0 240px' : '1 1 100%',
              maxHeight: screens.md ? '70vh' : 240,
              overflowY: 'auto',
              minWidth: 0,
            }}
            data-testid="asset-tree-panel"
          >
            <TypeTree
              nodes={tree}
              counts={ownCounts}
              total={counts.data?.total}
              selected={typeId ?? ALL_TYPES}
              onSelect={(id) => {
                setSelected([]);
                setParam('type', id === ALL_TYPES ? undefined : id);
              }}
            />
          </nav>
        )}
        <Flex vertical gap={8} style={{ flex: '1 1 480px', minWidth: 0 }}>
          <BulkActionsDialog
            assetIds={selected}
            open={bulkOpen}
            onClose={() => {
              setBulkOpen(false);
              setSelected([]);
            }}
          />
          <MergeDialog
            ids={selected.length === 2 ? [selected[0] ?? '', selected[1] ?? ''] : undefined}
            open={mergeOpen}
            onClose={() => {
              setMergeOpen(false);
              setSelected([]);
            }}
          />
          <Table<AssetRecord>
            size="small"
            rowKey="id"
            rowSelection={
              selectable
                ? {
                    // Pinned with the tag, at the start side (the width the table's sum counts).
                    fixed: startSide,
                    columnWidth: SELECT_WIDTH,
                    selectedRowKeys: selected,
                    // Labelled boxes; the header one is safe in antd's hidden measure row (axe
                    // label and aria-hidden-focus, found once the showcase had assets).
                    columnTitle: (
                      <SelectPageBox
                        checked={rows.length > 0 && selected.length === rows.length}
                        indeterminate={selected.length > 0 && selected.length < rows.length}
                        onChange={(checked) => {
                          setSelected(checked ? rows.map((r) => r.id).slice(0, BULK_MAX) : []);
                        }}
                        label={t('assets.bulk_move.select_page')}
                      />
                    ),
                    onChange: (keys) => {
                      setSelected(keys.map(String).slice(0, BULK_MAX));
                    },
                    getCheckboxProps: (row) => ({
                      title: t('assets.bulk_move.select_row', { name: row.tag ?? row.name }),
                    }),
                  }
                : undefined
            }
            pagination={false}
            components={widths.components}
            loading={list.isLoading}
            dataSource={rows}
            scroll={{ x: tableWidth }}
            locale={{
              // Nothing to say while the first page loads; a search or type with no match says so.
              emptyText: list.isLoading ? (
                <span />
              ) : (
                <EmptyText>
                  {t(
                    view === 'recently_discovered'
                      ? 'assets.views.discovered_empty'
                      : debounced.trim() !== '' || typeId !== undefined || view !== 'all'
                        ? 'assets.record.no_match'
                        : 'assets.record.none',
                  )}
                </EmptyText>
              ),
            }}
            onRow={(asset) => ({
              onClick: () => {
                if (!trash) void navigate(`/assets/${asset.id}`);
              },
              style: { cursor: !trash ? 'pointer' : undefined },
            })}
            columns={[
              {
                ...column('tag'),
                render: (_: unknown, asset: AssetRecord) => (
                  <bdi dir="ltr" data-testid={`asset-row-${asset.id}`}>
                    {asset.tag ?? ''}
                  </bdi>
                ),
              },
              {
                ...column('name'),
                render: (_: unknown, asset: AssetRecord) => (
                  <CellText title={asset.name}>{asset.name}</CellText>
                ),
              },
              {
                ...column('user'),
                render: (_: unknown, asset: AssetRecord) => (
                  <CellText>
                    <bdi dir="auto">{nameIn('people', asset.owner_user_id)}</bdi>
                  </CellText>
                ),
              },
              {
                ...column('department'),
                render: (_: unknown, asset: AssetRecord) => (
                  <CellText>
                    <bdi dir="auto">{departmentName(asset.department_id)}</bdi>
                  </CellText>
                ),
              },
              {
                ...column('parent'),
                render: (_: unknown, asset: AssetRecord) => (
                  <bdi dir="auto">{nameIn('parents', asset.parent_asset_id)}</bdi>
                ),
              },
              {
                ...column('product'),
                render: (_: unknown, asset: AssetRecord) => (
                  <CellText>
                    <bdi dir="auto">{nameIn('products', asset.product_id)}</bdi>
                  </CellText>
                ),
              },
              {
                ...column('type'),
                render: (_: unknown, asset: AssetRecord) => (
                  <CellText>{typeName(asset.product_type_id)}</CellText>
                ),
              },
              {
                ...column('site'),
                render: (_: unknown, asset: AssetRecord) =>
                  asset.site_id == null ? '' : <bdi dir="auto">{siteName(asset.site_id)}</bdi>,
              },
              {
                ...column('serial'),
                render: (_: unknown, asset: AssetRecord) => (
                  <bdi dir="ltr">{asset.serial_number ?? ''}</bdi>
                ),
              },
              {
                ...column('state'),
                render: (_: unknown, asset: AssetRecord) => (
                  <ToneTag tone="default">{stateName(asset.state_id)}</ToneTag>
                ),
              },
              ...(trash
                ? [
                    {
                      key: 'restore',
                      title: <span className="sr-only">{t('assets.admin.actions')}</span>,
                      render: (_: unknown, asset: AssetRecord) => (
                        <WriteButton
                          type="link"
                          onClick={(event) => {
                            event.stopPropagation();
                            restoreAsset(asset.id);
                          }}
                          data-testid={`asset-restore-${asset.id}`}
                        >
                          {t('assets.record.restore')}
                        </WriteButton>
                      ),
                    },
                  ]
                : []),
            ]}
          />
          {list.hasNextPage && (
            <Button
              onClick={() => {
                void list.fetchNextPage();
              }}
              loading={list.isFetchingNextPage}
              style={{ alignSelf: 'center' }}
            >
              {t('assets.admin.load_more')}
            </Button>
          )}
        </Flex>
      </Flex>
      <MyExportsButton button={false} open={myExportsOpen} onOpenChange={setMyExportsOpen} />
      <ImportWizard
        open={importOpen}
        onClose={() => {
          setImportOpen(false);
        }}
      />
      <Drawer
        open={adding !== undefined}
        title={t('assets.record.add')}
        width={640}
        destroyOnHidden
        onClose={closeAdding}
        extra={
          <WriteButton
            type="primary"
            loading={change.isPending}
            onClick={save}
            data-testid="asset-add-save"
          >
            {t('actions.save')}
          </WriteButton>
        }
        data-testid="asset-add-drawer"
      >
        <Problems problems={problems} testId="asset-add-problems" />
        {adding !== undefined && (
          <AssetFields
            creating
            draft={adding.draft}
            onChange={(draft) => {
              setAdding({ ...adding, draft });
            }}
          />
        )}
      </Drawer>
    </ListPage>
  );
}
