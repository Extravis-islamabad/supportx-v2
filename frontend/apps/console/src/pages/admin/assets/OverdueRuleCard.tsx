import {
  Alert,
  Card,
  Flex,
  Form,
  InputNumber,
  Select,
  Switch,
  Table,
  TreeSelect,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';

import {
  useAssetOverdueRule,
  useAssetOverdueRuleActions,
  useAssetOverdueRuns,
  useAssetOverdueStates,
  useAssetProductTypes,
  useAssetStates,
  type AssetOverdueRule,
  type AssetOverdueRuleInput,
  type AssetOverdueRun,
} from '@supportx/api-client';
import {
  FormProblem,
  loadedEmpty,
  useAppearance,
  useDateTime,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { nameOf } from './shared';
import { typeTree, type TypeNode } from './tree';

// The overdue-scan rule (WP-049b s3; REQ-AST-056), in the asset settings (config.assets): off by
// default; for chosen product types, an asset not scanned for N days moves to a state or to the
// trash (restorable, never deleted). Saving first shows how many assets it would change now
// (AC2); each run is listed with what it changed (AC1). Live: a save or a run refetches here.

interface Draft {
  enabled: boolean;
  days: number;
  action: AssetOverdueRule['action'];
  product_type_ids: string[];
  state_id: string | null;
}

function draftOf(rule: AssetOverdueRule): Draft {
  return {
    enabled: rule.enabled,
    days: rule.days,
    action: rule.action,
    product_type_ids: rule.product_type_ids,
    state_id: rule.state_id,
  };
}

function Runs() {
  const t = useLabel();
  const dates = useDateTime();
  const runs = useAssetOverdueRuns();
  return (
    <Table<AssetOverdueRun>
      size="small"
      rowKey="id"
      pagination={false}
      loading={runs.isPending}
      dataSource={runs.data ?? []}
      locale={{ emptyText: loadedEmpty(runs.isPending, t('assets.overdue.no_runs')) }}
      data-testid="asset-overdue-runs"
      columns={[
        {
          key: 'when',
          title: t('assets.overdue.ran_at'),
          render: (_, run) => dates.format(run.ran_at),
        },
        {
          key: 'what',
          title: t('assets.overdue.action'),
          render: (_, run) => t(`asset_overdue_action.${run.action}`),
        },
        {
          key: 'count',
          title: t('assets.overdue.changed'),
          render: (_, run) => t('assets.overdue.changed_count', { count: run.changed_count }),
        },
        {
          // Never forced (the life cycle): each skipped asset is kept in the run with why.
          key: 'skipped',
          title: t('assets.overdue.skipped'),
          render: (_, run) => {
            const skipped = run.changed.filter((c) => c.action === 'skipped');
            const reasons = [...new Set(skipped.map((c) => c.reason ?? 'transition_not_allowed'))];
            return skipped.length === 0 ? (
              ''
            ) : (
              <Flex vertical gap={0} data-testid={`asset-overdue-skipped-${run.id}`}>
                {t('assets.overdue.skipped_count', { count: skipped.length })}
                {reasons.map((r) => (
                  <Typography.Text key={r} type="secondary">
                    {t(`asset_overdue_skip.${r}`)}
                  </Typography.Text>
                ))}
              </Flex>
            );
          },
        },
      ]}
    />
  );
}

export function OverdueRuleCard() {
  const t = useLabel();
  const { locale } = useAppearance();
  const rule = useAssetOverdueRule();
  const types = useAssetProductTypes();
  const states = useAssetStates();
  const { preview, save } = useAssetOverdueRuleActions();
  const problem = useFormProblem();
  const [draft, setDraft] = useState<Draft>();
  const [count, setCount] = useState<number>();
  const tree = useMemo(() => typeTree(types.data ?? []), [types.data]);
  const current = draft ?? (rule.data === undefined ? undefined : draftOf(rule.data));
  // Only the states the life cycle of the chosen types reaches (the server refuses others).
  const reachable = useAssetOverdueStates(current?.product_type_ids ?? [], current !== undefined);
  if (rule.data === undefined || current === undefined) return null;
  const saved = rule.data;
  const set = (patch: Partial<Draft>) => {
    setDraft({ ...current, ...patch });
    setCount(undefined);
  };
  const choices = (nodes: TypeNode[]): object[] =>
    nodes.map((node) => ({
      value: node.id,
      title: nameOf(node.names, locale),
      children: choices(node.children ?? []),
    }));
  const body: AssetOverdueRuleInput = {
    ...current,
    state_id: current.action === 'move_state' ? current.state_id : null,
  };
  const check = () => {
    problem.clear();
    preview.mutate(body, {
      onSuccess: (answer) => {
        setCount(answer.count);
      },
      onError: problem.show,
    });
  };
  const store = () => {
    problem.clear();
    save.mutate(
      { version: saved.version, body },
      {
        onSuccess: () => {
          setDraft(undefined);
          setCount(undefined);
        },
        onError: problem.show,
      },
    );
  };
  const needsState =
    current.enabled && current.action === 'move_state' && current.state_id === null;
  return (
    <Card title={t('assets.overdue.title')} data-testid="asset-overdue-rule">
      <Flex vertical gap={16} style={{ maxWidth: 640 }}>
        <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
          {t('assets.overdue.help')}
        </Typography.Paragraph>
        <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
          {t('assets.overdue.lifecycle_note')}
        </Typography.Paragraph>
        <FormProblem problem={problem} />
        <Form layout="vertical">
          <Form.Item label={t('assets.overdue.enabled')} htmlFor="asset-overdue-enabled">
            <Switch
              id="asset-overdue-enabled"
              checked={current.enabled}
              onChange={(enabled) => {
                set({ enabled });
              }}
              data-testid="asset-overdue-enabled"
            />
          </Form.Item>
          <Form.Item label={t('assets.overdue.days')} htmlFor="asset-overdue-days">
            <InputNumber
              id="asset-overdue-days"
              min={1}
              max={3650}
              value={current.days}
              onChange={(days) => {
                if (days !== null) set({ days });
              }}
              data-testid="asset-overdue-days"
            />
          </Form.Item>
          <Form.Item label={t('assets.overdue.types')} htmlFor="asset-overdue-types">
            <TreeSelect
              id="asset-overdue-types"
              multiple
              value={current.product_type_ids}
              treeData={choices(tree)}
              onChange={(ids: string[]) => {
                set({ product_type_ids: ids });
              }}
              placeholder={t('assets.overdue.all_types')}
              data-testid="asset-overdue-types"
            />
          </Form.Item>
          <Form.Item label={t('assets.overdue.action')} htmlFor="asset-overdue-action">
            <Select
              id="asset-overdue-action"
              value={current.action}
              onChange={(action) => {
                set({ action });
              }}
              options={(['move_state', 'trash'] as const).map((a) => ({
                value: a,
                label: t(`asset_overdue_action.${a}`),
              }))}
              data-testid="asset-overdue-action"
            />
          </Form.Item>
          {current.action === 'move_state' && (
            <Form.Item label={t('assets.overdue.state')} htmlFor="asset-overdue-state">
              <Select
                id="asset-overdue-state"
                value={current.state_id}
                onChange={(state) => {
                  set({ state_id: state });
                }}
                options={(states.data ?? [])
                  .filter((s) => reachable.data?.state_ids.includes(s.id) === true)
                  .map((s) => ({ value: s.id, label: nameOf(s.names, locale) }))}
                data-testid="asset-overdue-state"
              />
            </Form.Item>
          )}
        </Form>
        {count !== undefined && (
          <Alert
            type={count > 0 ? 'warning' : 'info'}
            showIcon
            role="status"
            message={t('assets.overdue.preview_count', { count })}
            data-testid="asset-overdue-preview"
          />
        )}
        <Flex gap={8} wrap>
          <WriteButton
            onClick={check}
            loading={preview.isPending}
            disabled={needsState}
            whyDisabled={t('assets.overdue.state_first')}
            data-testid="asset-overdue-check"
          >
            {t('assets.overdue.check')}
          </WriteButton>
          {/* AC2: it is saved only after its effect now has been shown. */}
          <WriteButton
            type="primary"
            onClick={store}
            loading={save.isPending}
            disabled={draft === undefined || count === undefined}
            whyDisabled={t('assets.overdue.check_first')}
            data-testid="asset-overdue-save"
          >
            {t('actions.save')}
          </WriteButton>
        </Flex>
        <Typography.Title level={5} style={{ margin: 0 }}>
          {t('assets.overdue.runs')}
        </Typography.Title>
        <Runs />
      </Flex>
    </Card>
  );
}
