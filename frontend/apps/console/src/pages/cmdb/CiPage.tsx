import { useQueryClient } from '@tanstack/react-query';
import { Alert, App, Button, Flex, List, Modal, Result, TreeSelect, Typography } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router';

import {
  queryKeys,
  useChangeCiType,
  useCi,
  useCiHistory,
  useCiStates,
  useCiTypes,
  useCiTypeChangePreview,
  useCopyCi,
  useCustomFields,
  useDeleteCi,
  useUpdateCi,
  ApiError,
  type Ci,
} from '@supportx/api-client';
import { applyServerErrors, useForm, zodResolver } from '@supportx/forms';
import { useListFormat } from '@supportx/labels';
import { useRecordChannel } from '@supportx/realtime';
import {
  ConflictDialog,
  HeaderActions,
  NoAccess,
  NotInPlan,
  PropertiesPanel,
  PropertyList,
  RecordHeader,
  RecordPage,
  Tabs,
  WriteButton,
  reportError,
  restrictionOf,
  useAccess,
  useLicence,
  useAppearance,
  useDateTime,
  useConflict,
  useLabel,
} from '@supportx/ui';

import { CustomFieldValue } from '../customFields/fields';
import { fieldName, filled as hasValue } from '../customFields/values';
import { useCmdbRight } from './rights';
import { CiFields } from './CiForm';
import { CiMergeDrawer } from './CiMergeDrawer';
import { errorFields, patchOf, schema, valuesOf, type Values } from './form';
import { ImpactTab } from './map/ImpactTab';
import { MapTab } from './map/MapTab';
import { useSubscribersSection } from './useSubscribersSection';
import { VersionsTab } from './map/VersionsTab';
import { nameOf, typeTree } from './names';
import { refText } from './refNames';

// The record's tabs (template A): its details and history, its map (WP-053 S2) and its versions.
const TABS = ['details', 'map', 'impact', 'versions'] as const;
type TabKey = (typeof TABS)[number];

/** The CI's references, named in the properties panel (CMDB polish). */
const REFERENCES = [
  'site_id',
  'owner_user_id',
  'owner_group_id',
  'managed_by_group_id',
  'asset_id',
] as const;

/** One configuration item (template A, D-147): live, edited in place, with its history. */
export function CiPage() {
  const { id = '' } = useParams();
  const t = useLabel();
  const { can } = useAccess();
  const { has, isAdmin } = useLicence();
  const found = useCi(id);
  const queryClient = useQueryClient();
  useRecordChannel('ci', id, () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.detail(id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.history(id) });
    // A relationship added or removed gives the CI a new version (WP-053 S2).
    void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.versions(id) });
    // A business service's subscribers changed (0185): its own section refetches.
    void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.subscribers(id) });
  });
  if (!has('cmdb')) return <NotInPlan titleKey="nav.cmdb" isAdmin={isAdmin} />;
  if (!can('cmdb.view')) return <NoAccess titleKey="nav.cmdb" />;
  if (found.isPending) return null;
  // A merged CI's ID opens its survivor, when the reader may see it (REQ-CMDB-017 AC2).
  const survivor =
    found.error instanceof ApiError && found.error.code === 'cmdb_ci_merged'
      ? found.error.params.survivor_id
      : undefined;
  if (typeof survivor === 'string') return <Navigate to={`/cmdb/${survivor}`} replace />;
  if (found.isError) return <Result status="404" title={t('errors.cmdb_ci_not_found')} />;
  // Never keyed by version: someone else's save must not throw away an open edit (lane C's
  // #524 review); the edit resolves through the ConflictDialog instead.
  return <CiRecord ci={found.data} />;
}

function CiRecord({ ci }: { ci: Ci }) {
  const t = useLabel();
  const navigate = useNavigate();
  const { message, modal } = App.useApp();
  const { locale } = useAppearance();
  const may = useCmdbRight();
  const subscribers = useSubscribersSection(ci);
  const types = useCiTypes();
  const states = useCiStates();
  const [editing, setEditing] = useState(false);
  const [moving, setMoving] = useState(false);
  const [merging, setMerging] = useState(false);
  const { can } = useAccess();
  // The CI as it read when the edit began: its version is the one the save sends (If-Match).
  const [opened, setOpened] = useState<Ci>(ci);
  const conflict = useConflict();
  const update = useUpdateCi(ci.id);
  const copy = useCopyCi(ci.id);
  const remove = useDeleteCi(ci.id);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: valuesOf(ci) });
  // Live changes show at once while nobody edits; an open edit keeps what the person typed.
  useEffect(() => {
    if (!editing) form.reset(valuesOf(ci));
  }, [ci, editing, form]);
  const typeOf = types.data?.items.find((x) => x.id === ci.type_id);
  const stateOf = states.data?.items.find((x) => x.id === ci.state_id);
  const dateTime = useDateTime();
  const [params, setParams] = useSearchParams();
  const asked = params.get('tab');
  const tab: TabKey = TABS.find((key) => key === asked) ?? 'details';

  const save = (version: number) =>
    form.handleSubmit((values) => {
      update.mutate(
        { changes: patchOf(values, opened.custom), version },
        {
          onSuccess: () => {
            setEditing(false);
            void message.success(t('cmdb.saved'));
          },
          onError: (error) => {
            if (conflict.take(error)) return;
            if (!applyServerErrors(error, form.setError, errorFields(error))) reportError(error);
          },
        },
      );
    })();

  const details = editing ? (
    <Flex vertical gap={16}>
      <CiFields form={form} typeLocked readOnly={ci.read_only_fields} />
      <Flex gap={8} justify="end">
        <Button
          onClick={() => {
            setEditing(false);
            form.reset(valuesOf(ci));
          }}
        >
          {t('actions.cancel')}
        </Button>
        <WriteButton
          type="primary"
          loading={update.isPending}
          onClick={() => {
            void save(opened.version);
          }}
          data-testid="ci-save"
        >
          {t('actions.save')}
        </WriteButton>
      </Flex>
    </Flex>
  ) : (
    <Flex vertical gap={16}>
      {ci.description !== null && (
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
          <bdi>{ci.description}</bdi>
        </Typography.Paragraph>
      )}
      <CiCustomValues ci={ci} />
      <CiHistory id={ci.id} />
    </Flex>
  );

  return (
    <RecordPage
      testId="ci-record"
      header={
        <RecordHeader
          typeLabel={typeOf === undefined ? undefined : nameOf(t, locale, typeOf, 'cmdb_ci_type')}
          displayId={ci.display_id}
          title={ci.name}
          meta={[t(`cmdb_ci_source.${ci.source}`)]}
        />
      }
      actions={
        <HeaderActions
          testId="ci-actions"
          primary={
            ci.can_edit && !editing ? (
              <WriteButton
                type="primary"
                onClick={() => {
                  setOpened(ci);
                  setEditing(true);
                  // The edit is on the details tab.
                  if (tab !== 'details') setParams({ tab: 'details' }, { replace: true });
                }}
                data-testid="ci-edit"
              >
                {t('actions.edit')}
              </WriteButton>
            ) : undefined
          }
          more={[
            ...(may('add')
              ? [
                  {
                    key: 'copy',
                    label: t('cmdb.action.copy'),
                    testId: 'ci-copy',
                    onClick: () => {
                      copy.mutate(crypto.randomUUID(), {
                        onSuccess: (made) => {
                          void message.success(t('cmdb.copied', { id: made.display_id }));
                          void navigate(`/cmdb/${made.id}`);
                        },
                        onError: reportError,
                      });
                    },
                  },
                ]
              : []),
            ...(ci.can_edit
              ? [
                  {
                    key: 'type',
                    label: t('cmdb.action.change_type'),
                    testId: 'ci-change-type',
                    onClick: () => {
                      setMoving(true);
                    },
                  },
                ]
              : []),
            ...(can('cmdb.manage')
              ? [
                  {
                    key: 'merge',
                    label: t('cmdb.action.merge'),
                    testId: 'ci-merge',
                    onClick: () => {
                      setMerging(true);
                    },
                  },
                ]
              : []),
            ...(ci.can_delete
              ? [
                  {
                    key: 'delete',
                    label: t('cmdb.action.delete'),
                    danger: true,
                    testId: 'ci-delete',
                    onClick: () => {
                      modal.confirm({
                        title: t('cmdb.delete_confirm', { name: ci.name }),
                        content: t('cmdb.delete_confirm_detail'),
                        okText: t('cmdb.action.delete'),
                        okButtonProps: { danger: true, 'data-testid': 'ci-delete-ok' },
                        cancelText: t('actions.cancel'),
                        onOk: () =>
                          remove.mutateAsync(ci.version).then(() => {
                            void message.success(t('cmdb.deleted', { id: ci.display_id }));
                            void navigate('/cmdb');
                          }, reportError),
                      });
                    },
                  },
                ]
              : []),
          ]}
        />
      }
      panel={
        <PropertiesPanel
          testId="ci-panel"
          sections={[
            {
              key: 'properties',
              title: t('cmdb.section.properties'),
              children: (
                <PropertyList
                  items={[
                    {
                      key: 'state',
                      label: t('cmdb.field.state_id'),
                      content:
                        stateOf === undefined ? '' : nameOf(t, locale, stateOf, 'cmdb_ci_state'),
                      filled: true,
                    },
                    {
                      key: 'impact',
                      label: t('cmdb.field.business_impact'),
                      content:
                        ci.business_impact === null ? '' : t(`cmdb_impact.${ci.business_impact}`),
                      filled: ci.business_impact !== null,
                    },
                    {
                      key: 'criticality',
                      label: t('cmdb.field.criticality'),
                      content: ci.criticality === null ? '' : t(`cmdb_impact.${ci.criticality}`),
                      filled: ci.criticality !== null,
                    },
                    // The CI's references by the names the server gave this reader (CMDB
                    // polish): one it may not see says so, an empty one is listed as empty.
                    ...REFERENCES.map((name) => {
                      const id = ci[name];
                      const ref = id === null ? undefined : ci.names?.[id];
                      return ref?.restricted === true
                        ? {
                            key: name,
                            label: t(`cmdb.field.${name}`),
                            content: null,
                            filled: true,
                            restricted: 'hidden' as const,
                          }
                        : {
                            key: name,
                            label: t(`cmdb.field.${name}`),
                            content: id === null ? '' : <bdi>{refText(t, ci.names, id)}</bdi>,
                            filled: id !== null,
                          };
                    }),
                    {
                      key: 'updated',
                      label: t('cmdb.field.updated_at'),
                      content: <bdi>{dateTime.format(ci.updated_at)}</bdi>,
                      filled: true,
                    },
                  ]}
                />
              ),
            },
            ...(subscribers === null ? [] : [subscribers]),
          ]}
        />
      }
    >
      <Tabs
        activeKey={tab}
        onChange={(key) => {
          setParams({ tab: key }, { replace: true });
        }}
        items={[
          { key: 'details', label: t('cmdb.tab.details'), children: details },
          {
            key: 'map',
            label: t('cmdb.tab.map'),
            // Mounted only while open: the map follows its channel only when someone looks.
            children: tab === 'map' ? <MapTab ci={ci} /> : null,
          },
          {
            key: 'impact',
            label: t('cmdb.tab.impact'),
            children: tab === 'impact' ? <ImpactTab ciId={ci.id} /> : null,
          },
          {
            key: 'versions',
            label: t('cmdb.tab.versions'),
            children: tab === 'versions' ? <VersionsTab ciId={ci.id} /> : null,
          },
        ]}
        data-testid="ci-tabs"
      />
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        opened={opened}
        latest={ci}
        fieldLabel={(field) => t(`cmdb.field.${field}`)}
        onReload={() => {
          conflict.clear();
          setOpened(ci);
          setEditing(false);
          form.reset(valuesOf(ci));
        }}
        onKeepMine={() => {
          const version = conflict.latestVersion ?? ci.version;
          conflict.clear();
          setOpened(ci);
          void save(version);
        }}
      />
      {merging && (
        <CiMergeDrawer
          ci={ci}
          onClose={() => {
            setMerging(false);
          }}
        />
      )}
      {moving && (
        <ChangeType
          ci={ci}
          onClose={() => {
            setMoving(false);
          }}
        />
      )}
    </RecordPage>
  );
}

/**
 * The CI's custom values (0175): the fields of its type and the types above it, each by its name
 * in the person's language. Masked ones say so (ADR-047); hidden ones never reach the page.
 */
function CiCustomValues({ ci }: { ci: Ci }) {
  const { locale } = useAppearance();
  const fields = useCustomFields('ci', false, true, { typeId: ci.type_id });
  const shown = (fields.data ?? []).filter(
    (f) => hasValue(ci.custom[f.key]) || ci.masked_fields.includes(`custom.${f.key}`),
  );
  if (shown.length === 0) return null;
  return (
    <PropertyList
      testId="ci-custom-values"
      items={shown.map((f) => ({
        key: f.key,
        label: <bdi dir="auto">{fieldName(f, locale)}</bdi>,
        content: <CustomFieldValue field={f} value={ci.custom[f.key]} />,
        filled: true,
        // The shared row says "masked" itself (ADR-047), as records of other kinds do.
        restricted: restrictionOf(ci, `custom.${f.key}`),
        testId: `ci-custom-${f.key}`,
      }))}
    />
  );
}

/**
 * Move the CI to another type (REQ-CMDB-003). The preview names the custom values the new type
 * would drop (0175); the move then asks to confirm, and history names the fields, never values.
 */
function ChangeType({ ci, onClose }: { ci: Ci; onClose: () => void }) {
  const t = useLabel();
  const { message } = App.useApp();
  const { locale } = useAppearance();
  const list = useListFormat();
  const types = useCiTypes();
  const change = useChangeCiType(ci.id);
  const [typeId, setTypeId] = useState<string>();
  const preview = useCiTypeChangePreview(ci.id, typeId);
  const dropped = preview.data?.dropped ?? [];
  const blocked = preview.data?.blocked === true;
  const tree = useMemo(
    () => typeTree(types.data?.items ?? [], (x) => nameOf(t, locale, x, 'cmdb_ci_type')),
    [types.data, t, locale],
  );
  return (
    <Modal
      open
      title={t('cmdb.action.change_type')}
      onCancel={onClose}
      okText={dropped.length > 0 ? t('cmdb.action.change_type_drop') : t('cmdb.action.change_type')}
      okButtonProps={{
        disabled: typeId === undefined || preview.isPending || blocked,
        danger: dropped.length > 0,
        // A danger button that drops values is outlined, not filled: the dark theme's red fill
        // with white text is below 4.5:1 (axe, run 44411932381; as the erasure screens).
        ...(dropped.length > 0 ? { type: 'default' as const } : {}),
        loading: change.isPending,
        ...({ 'data-testid': 'ci-change-type-ok' } as Record<string, string>),
      }}
      onOk={() => {
        if (typeId === undefined) return;
        change.mutate(
          { typeId, version: ci.version, confirmDropped: dropped.length > 0 },
          {
            onSuccess: () => {
              void message.success(t('cmdb.type_changed'));
              onClose();
            },
            onError: (error) => {
              // Someone added a value meanwhile: show the fresh preview instead of a toast.
              if (error instanceof ApiError && error.code === 'cmdb_ci_type_change_drops_fields') {
                void preview.refetch();
                return;
              }
              reportError(error);
            },
          },
        );
      }}
    >
      <Flex vertical gap={12}>
        <TreeSelect
          aria-label={t('cmdb.field.type_id')}
          treeDefaultExpandAll
          value={typeId}
          onChange={(next: string) => {
            setTypeId(next);
          }}
          treeData={tree}
          // Inside the dialog, so the list moves with it: opened during the dialog's zoom, a list
          // on the page body was placed against the half-scaled field (lane C, #550).
          getPopupContainer={(node: HTMLElement) => node.parentElement ?? document.body}
          style={{ width: '100%' }}
          data-testid="ci-new-type"
        />
        {blocked && (
          <Alert
            type="error"
            showIcon
            role="alert"
            message={t('cmdb.change_type_blocked')}
            data-testid="ci-change-type-blocked"
          />
        )}
        {!blocked && dropped.length > 0 && (
          <Alert
            type="warning"
            showIcon
            role="status"
            message={t('cmdb.change_type_drops', { count: dropped.length })}
            description={
              <bdi dir="auto" data-testid="ci-change-type-dropped">
                {list(dropped.map((d) => fieldName({ labels: d.labels }, locale)))}
              </bdi>
            }
            data-testid="ci-change-type-drops"
          />
        )}
      </Flex>
    </Modal>
  );
}

function CiHistory({ id }: { id: string }) {
  const t = useLabel();
  const list = useListFormat();
  // The person's own time zone, as every other history (lane C, #524).
  const dates = useDateTime();
  const history = useCiHistory(id);
  const { locale } = useAppearance();
  // Fields removed since are named too: old saves still mention them (0175).
  const custom = useCustomFields('ci', true);
  const fieldLabel = (field: string) => {
    if (!field.startsWith('custom.')) return t(`cmdb.field.${field}`);
    const found = custom.data?.find((f) => `custom.${f.key}` === field);
    return found === undefined ? t('cmdb.field.custom_field') : fieldName(found, locale);
  };
  const entries = history.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <List
      data-testid="ci-history"
      header={t('cmdb.history')}
      dataSource={entries}
      renderItem={(entry) => (
        <List.Item>
          <Typography.Text>
            {/* Each part isolated, so right to left never splits a date around a name. */}
            <bdi>{t(`change_kind.${entry.kind}`)}</bdi> ·{' '}
            <bdi>{entry.actor_name ?? t(`actor_type.${entry.actor_type}`)}</bdi> ·{' '}
            <bdi>{dates.format(entry.occurred_at)}</bdi>
            {entry.changes.length > 0 && (
              <>
                {' · '}
                <bdi>{list(entry.changes.map((c) => fieldLabel(c.field)))}</bdi>
              </>
            )}
          </Typography.Text>
        </List.Item>
      )}
    />
  );
}
