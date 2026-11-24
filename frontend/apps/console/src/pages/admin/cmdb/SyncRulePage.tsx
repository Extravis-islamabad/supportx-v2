import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Descriptions,
  Flex,
  Form,
  Input,
  Select,
  Space,
  Switch,
  Table,
  TreeSelect,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router';

import {
  queryKeys,
  useAssetProductTypes,
  useAssetStates,
  useCiStates,
  useCiTypes,
  useCreateSyncRule,
  useCustomFields,
  usePreviewSyncRule,
  useStartSyncRun,
  useSyncFields,
  useSyncRule,
  useSyncRun,
  useSyncRuns,
  useUnits,
  useUpdateSyncRule,
  type SyncPreview,
  type SyncRuleInput,
  type SyncRun,
  type SyncRunItem,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { useTenantChannel } from '@supportx/realtime';
import {
  Drawer,
  FieldRow,
  FormPage,
  FormProblem,
  FormSection,
  NoAccess,
  ToneTag,
  WriteButton,
  lengthLimit,
  loadedEmpty,
  reportError,
  useAccess,
  useAppearance,
  useDateTime,
  useFormProblem,
  useLabel,
  usePageCrumbs,
} from '@supportx/ui';

import { fieldName } from '../../customFields/values';
import { nameOf, typeTree } from '../../cmdb/names';
import { nameOf as assetName } from '../assets/shared';
import { SYNC_RULES_PATH, filterOf, simpleOf, syncRuleHref, type SimpleFilter } from './syncShared';

interface Draft {
  name: string;
  targetTypeId?: string;
  targetStateId?: string;
  enabled: boolean;
  /** CI attribute → asset field, in the order shown. */
  map: { target: string; source?: string }[];
  filter: SimpleFilter;
  /** A stored filter the editor cannot show as choices (made through the API): kept as it is. */
  rawFilter: unknown;
}

const EMPTY: Draft = {
  name: '',
  enabled: false,
  map: [{ target: 'name', source: 'name' }],
  filter: { productTypeIds: [], siteIds: [], stateIds: [] },
  rawFilter: null,
};

function bodyOf(draft: Draft): SyncRuleInput {
  return {
    name: draft.name.trim(),
    target_type_id: draft.targetTypeId ?? '',
    target_state_id: draft.targetStateId ?? null,
    enabled: draft.enabled,
    field_map: Object.fromEntries(
      draft.map.filter((m) => m.source !== undefined).map((m) => [m.target, m.source ?? '']),
    ),
    filter:
      draft.rawFilter === null
        ? filterOf(draft.filter)
        : (draft.rawFilter as SyncRuleInput['filter']),
  };
}

/**
 * Admin › CMDB › Sync rule (WP-053 S4a, REQ-CMDB-015; template B): which assets, which CI type,
 * and how the fields map. Preview shows (in a drawer) what the rule would do now, as you may see
 * it, before anything is saved; a saved rule lists its runs, each opening its items. A value a
 * stronger source set (by hand, by default) is kept, never overwritten (REQ-CMDB-016).
 */
export function SyncRulePage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { ruleId } = useParams();
  const editing = ruleId !== undefined && ruleId !== 'new' ? ruleId : undefined;
  const allowed = can('cmdb.configure');
  const loaded = useSyncRule(allowed ? editing : undefined);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [dirty, setDirty] = useState(false);
  const [preview, setPreview] = useState<SyncPreview>();
  const [key] = useState(() => crypto.randomUUID());
  const problem = useFormProblem();
  const create = useCreateSyncRule();
  const update = useUpdateSyncRule();
  const previewing = usePreviewSyncRule();
  const types = useCiTypes(allowed);
  const states = useCiStates(allowed);
  const fields = useSyncFields(draft.targetTypeId, allowed);
  const customFields = useCustomFields('ci', false, allowed && draft.targetTypeId !== undefined, {
    typeId: draft.targetTypeId,
  });
  const productTypes = useAssetProductTypes(allowed);
  const assetStates = useAssetStates(allowed);
  const sites = useUnits('sites', allowed && can('sites.view'));
  usePageCrumbs([
    { label: t('nav.admin_cmdb'), path: '/admin/cmdb' },
    { label: t('cmdb.sync.title'), path: SYNC_RULES_PATH },
    { label: loaded.data?.name ?? t('cmdb.sync.new') },
  ]);
  useTenantChannel(
    (m) => {
      if (m.covered === true) return; // a refresh: `covers` refetched it
      if (m.type === 'cmdb.sync_changed') {
        void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.sync.all });
      }
    },
    { covers: [queryKeys.cmdb.sync.all] },
  );
  // The saved rule into the form when it loads or changes elsewhere (live), unless the person
  // has unsaved changes: adjusted during render, as React advises for state that follows props.
  const [shown, setShown] = useState<number>();
  const rule = loaded.data;
  if (rule !== undefined && !dirty && shown !== rule.version) {
    const simple = simpleOf(rule.filter);
    setShown(rule.version);
    setDraft({
      name: rule.name,
      targetTypeId: rule.target_type_id,
      targetStateId: rule.target_state_id ?? undefined,
      enabled: rule.enabled,
      map: Object.entries(rule.field_map).map(([target, source]) => ({ target, source })),
      filter: simple ?? EMPTY.filter,
      rawFilter: simple === null ? rule.filter : null,
    });
  }
  const tree = useMemo(
    () =>
      typeTree(types.data?.items ?? [], (x) => nameOf(t, locale, x, 'cmdb_ci_type'), {
        counts: false,
      }),
    [types.data, t, locale],
  );
  if (!allowed) return <NoAccess titleKey="cmdb.sync.title" />;
  if (editing !== undefined && loaded.isLoading) return null;

  const set = (changes: Partial<Draft>) => {
    setDraft((d) => ({ ...d, ...changes }));
    setDirty(true);
  };
  const targetLabel = (target: string) => {
    if (!target.startsWith('custom.')) return t(`cmdb.field.${target}`);
    const found = customFields.data?.find((f) => `custom.${f.key}` === target);
    return found === undefined ? t('cmdb.sync.removed_field') : fieldName(found, locale);
  };
  const kindOf = (target: string) => fields.data?.ci_attributes.find((a) => a.key === target)?.kind;
  // A target whose kind is unknown (a custom field removed since the rule was saved) still offers
  // every asset field, so its chosen source shows by name, never as its key (rule d; lane C).
  const sourcesFor = (target: string) => {
    const kind = kindOf(target);
    return (fields.data?.asset_fields ?? [])
      .filter((f) => kind === undefined || f.kind === kind)
      .map((f) => ({ value: f.key, label: t(`cmdb.sync.asset_field.${f.key}`) }));
  };
  const unmapped = (fields.data?.ci_attributes ?? []).filter(
    (a) => !draft.map.some((m) => m.target === a.key),
  );
  const ready = draft.name.trim() !== '' && draft.targetTypeId !== undefined;
  const failed = (error: unknown) => {
    problem.show(error);
  };
  const save = () => {
    const body = bodyOf(draft);
    if (editing === undefined) {
      create.mutate(
        { body, key },
        {
          onSuccess: (made) => {
            void message.success(t('cmdb.sync.saved'));
            setDirty(false);
            void navigate(syncRuleHref(made.id), { replace: true });
          },
          onError: failed,
        },
      );
      return;
    }
    update.mutate(
      { id: editing, body, version: loaded.data?.version ?? 0 },
      {
        onSuccess: () => {
          void message.success(t('cmdb.sync.saved'));
          setDirty(false);
        },
        onError: failed,
      },
    );
  };
  return (
    <FormPage
      testId="cmdb-sync-rule"
      title={loaded.data?.name ?? t('cmdb.sync.new')}
      description={t('cmdb.sync.editor_description')}
      back={{ label: t('cmdb.sync.title'), onClick: () => void navigate(SYNC_RULES_PATH) }}
      cancel={
        <Button onClick={() => void navigate(SYNC_RULES_PATH)} data-testid="cmdb-sync-cancel">
          {t('actions.cancel')}
        </Button>
      }
      primary={
        <WriteButton
          type="primary"
          loading={create.isPending || update.isPending}
          disabled={!dirty || !ready}
          whyDisabled={t(ready ? 'why.nothing_changed' : 'cmdb.sync.why.incomplete')}
          onClick={save}
          data-testid="cmdb-sync-save"
        >
          {t('actions.save')}
        </WriteButton>
      }
      extra={
        <Button
          disabled={!ready}
          loading={previewing.isPending}
          onClick={() => {
            previewing.mutate(bodyOf(draft), { onSuccess: setPreview, onError: failed });
          }}
          data-testid="cmdb-sync-preview"
        >
          {t('cmdb.sync.preview')}
        </Button>
      }
    >
      <FormProblem problem={problem} />
      <FormSection title={t('cmdb.sync.section.rule')} testId="cmdb-sync-section-rule">
        <Form layout="vertical">
          <Form.Item label={t('cmdb.sync.name')} htmlFor="cmdb-sync-name" required>
            <Input
              id="cmdb-sync-name"
              count={lengthLimit(200)}
              value={draft.name}
              onChange={(e) => {
                set({ name: e.target.value });
              }}
              data-testid="cmdb-sync-name"
            />
          </Form.Item>
          <FieldRow>
            <Form.Item label={t('cmdb.sync.target_type')} htmlFor="cmdb-sync-type" required>
              <TreeSelect
                id="cmdb-sync-type"
                treeData={tree}
                treeDefaultExpandAll
                value={draft.targetTypeId}
                onChange={(value: string) => {
                  // Custom targets belong to a type: they go when the type changes.
                  set({
                    targetTypeId: value,
                    map: draft.map.filter((m) => !m.target.startsWith('custom.')),
                  });
                }}
                data-testid="cmdb-sync-type"
              />
            </Form.Item>
            <Form.Item label={t('cmdb.sync.target_state')} htmlFor="cmdb-sync-state">
              <Select
                id="cmdb-sync-state"
                allowClear
                placeholder={t('cmdb.sync.default_state')}
                value={draft.targetStateId}
                onChange={(value?: string) => {
                  set({ targetStateId: value });
                }}
                options={(states.data?.items ?? []).map((s) => ({
                  value: s.id,
                  label: nameOf(t, locale, s, 'cmdb_ci_state'),
                }))}
                data-testid="cmdb-sync-state"
              />
            </Form.Item>
          </FieldRow>
          <Form.Item label={t('cmdb.sync.enabled')} htmlFor="cmdb-sync-enabled">
            <Space>
              <Switch
                id="cmdb-sync-enabled"
                checked={draft.enabled}
                onChange={(on) => {
                  set({ enabled: on });
                }}
                data-testid="cmdb-sync-enabled"
              />
              <Typography.Text type="secondary">{t('cmdb.sync.enabled_help')}</Typography.Text>
            </Space>
          </Form.Item>
        </Form>
      </FormSection>
      <FormSection
        title={t('cmdb.sync.section.assets')}
        description={t('cmdb.sync.section.assets_help')}
        testId="cmdb-sync-section-assets"
      >
        {draft.rawFilter !== null ? (
          <Alert
            type="info"
            showIcon
            message={t('cmdb.sync.custom_filter')}
            action={
              <Button
                size="small"
                onClick={() => {
                  set({ rawFilter: null });
                }}
                data-testid="cmdb-sync-replace-filter"
              >
                {t('cmdb.sync.replace_filter')}
              </Button>
            }
          />
        ) : (
          <Form layout="vertical">
            <FieldRow>
              <Form.Item label={t('cmdb.sync.product_types')} htmlFor="cmdb-sync-product-types">
                <Select
                  id="cmdb-sync-product-types"
                  mode="multiple"
                  allowClear
                  placeholder={t('cmdb.sync.any')}
                  value={draft.filter.productTypeIds}
                  onChange={(value: string[]) => {
                    set({ filter: { ...draft.filter, productTypeIds: value } });
                  }}
                  options={(productTypes.data ?? []).map((p) => ({
                    value: p.id,
                    label: assetName(p.names, locale),
                  }))}
                  optionFilterProp="label"
                  data-testid="cmdb-sync-product-types"
                />
              </Form.Item>
              <Form.Item label={t('cmdb.sync.sites')} htmlFor="cmdb-sync-sites">
                <Select
                  id="cmdb-sync-sites"
                  mode="multiple"
                  allowClear
                  placeholder={t('cmdb.sync.any')}
                  value={draft.filter.siteIds}
                  onChange={(value: string[]) => {
                    set({ filter: { ...draft.filter, siteIds: value } });
                  }}
                  options={(sites.data ?? []).map((s) => ({ value: s.id, label: s.name }))}
                  optionFilterProp="label"
                  data-testid="cmdb-sync-sites"
                />
              </Form.Item>
              <Form.Item label={t('cmdb.sync.asset_states')} htmlFor="cmdb-sync-asset-states">
                <Select
                  id="cmdb-sync-asset-states"
                  mode="multiple"
                  allowClear
                  placeholder={t('cmdb.sync.any')}
                  value={draft.filter.stateIds}
                  onChange={(value: string[]) => {
                    set({ filter: { ...draft.filter, stateIds: value } });
                  }}
                  options={(assetStates.data ?? []).map((s) => ({
                    value: s.id,
                    label: assetName(s.names, locale),
                  }))}
                  optionFilterProp="label"
                  data-testid="cmdb-sync-asset-states"
                />
              </Form.Item>
            </FieldRow>
          </Form>
        )}
      </FormSection>
      <FormSection
        title={t('cmdb.sync.section.fields')}
        description={t('cmdb.sync.section.fields_help')}
        testId="cmdb-sync-section-fields"
      >
        <Flex vertical gap={8}>
          {draft.map.map((row, index) => (
            <Flex
              key={row.target}
              gap={8}
              align="center"
              wrap
              data-testid={`cmdb-sync-map-${row.target}`}
            >
              <Typography.Text style={{ minWidth: 180 }}>
                <bdi dir="auto">{targetLabel(row.target)}</bdi>
              </Typography.Text>
              <Select
                style={{ minWidth: 220 }}
                aria-label={t('cmdb.sync.asset_field_for', { field: targetLabel(row.target) })}
                value={row.source}
                onChange={(value: string) => {
                  set({
                    map: draft.map.map((m, i) => (i === index ? { ...m, source: value } : m)),
                  });
                }}
                options={sourcesFor(row.target)}
                // Whatever the options, the chosen source reads by its label, never its key.
                labelRender={({ value }) => t(`cmdb.sync.asset_field.${String(value)}`)}
                data-testid={`cmdb-sync-source-${row.target}`}
              />
              {row.target !== 'name' && (
                <Button
                  type="text"
                  icon={<DeleteOutlined />}
                  aria-label={t('cmdb.sync.remove_mapping', { field: targetLabel(row.target) })}
                  onClick={() => {
                    set({ map: draft.map.filter((_, i) => i !== index) });
                  }}
                  data-testid={`cmdb-sync-unmap-${row.target}`}
                />
              )}
            </Flex>
          ))}
          {unmapped.length > 0 && (
            <Select
              style={{ maxWidth: 320 }}
              value={null}
              placeholder={
                <Space>
                  <PlusOutlined />
                  {t('cmdb.sync.add_mapping')}
                </Space>
              }
              aria-label={t('cmdb.sync.add_mapping')}
              onChange={(target: string) => {
                set({ map: [...draft.map, { target }] });
              }}
              options={unmapped.map((a) => ({ value: a.key, label: targetLabel(a.key) }))}
              data-testid="cmdb-sync-add-mapping"
            />
          )}
        </Flex>
      </FormSection>
      {editing !== undefined && (
        <RunsSection ruleId={editing} customName={(key) => targetLabel(`custom.${key}`)} />
      )}
      <Drawer
        open={preview !== undefined}
        size="large"
        title={t('cmdb.sync.preview_title')}
        onClose={() => {
          setPreview(undefined);
        }}
        data-testid="cmdb-sync-preview-drawer"
      >
        {preview !== undefined && <PreviewBody preview={preview} targetLabel={targetLabel} />}
      </Drawer>
    </FormPage>
  );
}

const OUTCOMES = ['created', 'updated', 'kept', 'unchanged', 'failed'] as const;

function Counts({ counts }: { counts: Record<string, number> }) {
  const t = useLabel();
  return (
    <Descriptions
      size="small"
      column={{ xs: 2, sm: 3, md: 5 }}
      items={OUTCOMES.map((o) => ({
        key: o,
        label: t(`cmdb_sync_outcome.${o}`),
        children: counts[o] ?? 0,
      }))}
    />
  );
}

function PreviewBody({
  preview,
  targetLabel,
}: {
  preview: SyncPreview;
  targetLabel: (target: string) => string;
}) {
  const t = useLabel();
  const list = useListFormat();
  return (
    <Flex vertical gap={12} data-testid="cmdb-sync-preview-body">
      <Typography.Text>
        {t(preview.complete ? 'cmdb.sync.preview_total' : 'cmdb.sync.preview_partial', {
          count: preview.total,
        })}
      </Typography.Text>
      <Counts counts={preview.counts} />
      <Table
        rowKey="asset_id"
        size="small"
        pagination={false}
        dataSource={preview.items}
        locale={{ emptyText: t('cmdb.sync.preview_empty') }}
        columns={[
          {
            key: 'asset',
            title: t('cmdb.sync.asset'),
            render: (_, i) => (
              <bdi dir="auto">{[i.asset_tag, i.asset_name].filter(Boolean).join(' ')}</bdi>
            ),
          },
          {
            key: 'outcome',
            title: t('cmdb.sync.outcome'),
            render: (_, i) => t(`cmdb_sync_outcome.${i.outcome}`),
          },
          {
            key: 'changes',
            title: t('cmdb.sync.changes'),
            render: (_, i) => list(i.changes.map(targetLabel)),
          },
          {
            key: 'kept',
            title: t('cmdb.sync.kept'),
            render: (_, i) => list(i.kept.map(targetLabel)),
          },
        ]}
      />
    </Flex>
  );
}

function RunsSection({
  ruleId,
  customName,
}: {
  ruleId: string;
  customName: (key: string) => string;
}) {
  const t = useLabel();
  const dateTime = useDateTime();
  const { message } = App.useApp();
  const runs = useSyncRuns(ruleId);
  const start = useStartSyncRun();
  const [open, setOpen] = useState<string>();
  return (
    <FormSection title={t('cmdb.sync.section.runs')} testId="cmdb-sync-section-runs">
      <Flex vertical gap={8}>
        <div>
          <WriteButton
            loading={start.isPending}
            onClick={() => {
              start.mutate(
                { ruleId, key: crypto.randomUUID() },
                {
                  onSuccess: () => void message.success(t('cmdb.sync.run_queued')),
                  onError: reportError,
                },
              );
            }}
            data-testid="cmdb-sync-run-now"
          >
            {t('cmdb.sync.run_now')}
          </WriteButton>
        </div>
        <Table<SyncRun>
          rowKey="id"
          size="small"
          pagination={false}
          loading={runs.isPending}
          dataSource={runs.data?.items ?? []}
          locale={{ emptyText: loadedEmpty(runs.isPending, t('cmdb.sync.no_runs')) }}
          scroll={{ x: 640 }}
          data-testid="cmdb-sync-runs"
          columns={[
            {
              key: 'when',
              title: t('cmdb.sync.when'),
              render: (_, r) => (
                <Button
                  type="link"
                  style={{ padding: 0 }}
                  onClick={() => {
                    setOpen(r.id);
                  }}
                  data-testid={`cmdb-sync-run-${r.id}`}
                >
                  <bdi>{dateTime.format(r.started_at ?? r.created_at)}</bdi>
                </Button>
              ),
            },
            {
              key: 'trigger',
              title: t('cmdb.sync.trigger'),
              render: (_, r) => t(`cmdb_sync_trigger.${r.trigger}`),
            },
            {
              key: 'status',
              title: t('cmdb.sync.status'),
              render: (_, r) => (
                <ToneTag
                  tone={
                    r.status === 'failed' ? 'error' : r.status === 'succeeded' ? 'success' : 'info'
                  }
                >
                  {t(`cmdb_sync_run_status.${r.status}`)}
                </ToneTag>
              ),
            },
            {
              key: 'counts',
              title: t('cmdb.sync.counts'),
              // Blank for a reader the server withholds totals from (they count records
              // outside that reader's reach).
              render: (_, r) =>
                r.created_count === null ||
                r.updated_count === null ||
                r.kept_count === null ||
                r.failed_count === null
                  ? ''
                  : t('cmdb.sync.counts_line', {
                      created: r.created_count,
                      updated: r.updated_count,
                      kept: r.kept_count,
                      failed: r.failed_count,
                    }),
            },
          ]}
        />
      </Flex>
      <Drawer
        open={open !== undefined}
        size="large"
        title={t('cmdb.sync.run_title')}
        onClose={() => {
          setOpen(undefined);
        }}
        data-testid="cmdb-sync-run-drawer"
      >
        {open !== undefined && <RunBody runId={open} customName={customName} />}
      </Drawer>
    </FormSection>
  );
}

function RunBody({ runId, customName }: { runId: string; customName: (key: string) => string }) {
  const t = useLabel();
  const list = useListFormat();
  const run = useSyncRun(runId);
  if (run.data === undefined) return null;
  const data = run.data;
  const restricted = <ToneTag tone="default">{t('cmdb.sync.restricted')}</ToneTag>;
  return (
    <Flex vertical gap={12} data-testid="cmdb-sync-run-body">
      {data.failure !== null && (
        <Alert type="error" showIcon message={t(`cmdb_sync_failure.${data.failure}`)} />
      )}
      {data.skipped_targets.length > 0 && (
        // Lane C (a): fields that stopped being plain since the rule was saved were left alone.
        <Alert
          type="warning"
          showIcon
          message={t('cmdb.sync.skipped_targets', { count: data.skipped_targets.length })}
          description={list(data.skipped_targets.map(customName))}
          data-testid="cmdb-sync-skipped-targets"
        />
      )}
      {data.created_count === null ? (
        <Alert
          type="info"
          showIcon
          message={t('cmdb.sync.totals_hidden')}
          data-testid="cmdb-sync-totals-hidden"
        />
      ) : (
        <Counts
          counts={{
            created: data.created_count,
            updated: data.updated_count ?? 0,
            kept: data.kept_count ?? 0,
            unchanged: data.unchanged_count ?? 0,
            failed: data.failed_count ?? 0,
          }}
        />
      )}
      <Table<SyncRunItem>
        rowKey={(i) => `${i.asset_id ?? 'x'}-${i.ci_id ?? 'y'}-${i.outcome}`}
        size="small"
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        dataSource={data.items}
        locale={{ emptyText: t('cmdb.sync.run_empty') }}
        columns={[
          {
            key: 'asset',
            title: t('cmdb.sync.asset'),
            render: (_, i) =>
              i.asset_restricted ? restricted : <bdi dir="auto">{i.asset_label ?? ''}</bdi>,
          },
          {
            key: 'ci',
            title: t('cmdb.sync.ci'),
            render: (_, i) =>
              i.ci_restricted ? restricted : <bdi dir="auto">{i.ci_label ?? ''}</bdi>,
          },
          {
            key: 'outcome',
            title: t('cmdb.sync.outcome'),
            render: (_, i) => t(`cmdb_sync_outcome.${i.outcome}`),
          },
          {
            key: 'detail',
            title: t('cmdb.sync.detail'),
            render: (_, i) =>
              i.code !== null
                ? t(`errors.field.${i.code}`)
                : i.kept.length > 0
                  ? t('cmdb.sync.kept_fields', { count: i.kept.length })
                  : '',
          },
        ]}
      />
    </Flex>
  );
}
