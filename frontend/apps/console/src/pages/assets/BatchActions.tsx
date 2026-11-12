import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Flex,
  Form,
  Input,
  Modal,
  Progress,
  Radio,
  Select,
  Table,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';

import {
  ASSET_BULK_PROGRESS,
  assetBatchKeys,
  useAssetBulkJob,
  useAssetMergePreview,
  useAssetProduct,
  useAssetStates,
  useMergeAssets,
  useStartAssetBulk,
  useUnits,
  useVendors,
  type AssetBulkAction,
  type AssetBulkResult,
  type AssetMergeField,
  type AssetMergeSide,
} from '@supportx/api-client';
import { usePersonalChannel } from '@supportx/realtime';
import { lengthLimit, useAppearance, useDateTime, useLabel } from '@supportx/ui';

import { nameOf } from '../admin/assets/shared';
import { DepartmentPicker, UserPicker } from '../incidents/pickers';
import { okFooter } from './dialogOk';
import { useSiteNames } from './live';
import { bulkChanges, reasonText } from './batch';
import { problemText } from './problemText';

// Bulk actions and merging duplicates on the asset list (WP-049b S4b; REQ-AST-051, 052).
// A bulk job runs on the server, as you, one asset at a time; its progress and per-asset results
// arrive live on your own channel. A merge shows each field side by side first.

const ACTIONS: AssetBulkAction[] = ['edit', 'move', 'assign', 'delete'];
const TEXT_MAX = 200;

/** The job's progress, live: the person's channel says when it moved on. */
function useBulkJobLive(jobId: string | undefined) {
  const queryClient = useQueryClient();
  usePersonalChannel((message) => {
    if (jobId === undefined || message.type !== ASSET_BULK_PROGRESS) return;
    if (!message.ids.includes(jobId)) return;
    void queryClient.invalidateQueries({ queryKey: assetBatchKeys.bulkJob(jobId) });
  });
  return useAssetBulkJob(jobId);
}

export function BulkProgress({ jobId }: { jobId: string }) {
  const t = useLabel();
  const job = useBulkJobLive(jobId);
  const data = job.data;
  if (data === undefined) return null;
  const percent = data.total === 0 ? 0 : Math.round((data.processed / data.total) * 100);
  const skipped = data.results.filter((r) => r.outcome === 'skipped');
  return (
    <Flex vertical gap={12} data-testid="asset-bulk-progress">
      <Typography.Text>{t(`asset_bulk_status.${data.status}`)}</Typography.Text>
      <Progress
        percent={percent}
        status={data.status === 'failed' ? 'exception' : undefined}
        aria-label={t('assets.bulk.progress', { processed: data.processed, total: data.total })}
      />
      <Typography.Text data-testid="asset-bulk-summary">
        {data.status === 'done' || data.status === 'failed'
          ? t('assets.bulk.summary', { done: data.done_count, skipped: data.skipped_count })
          : t('assets.bulk.progress', { processed: data.processed, total: data.total })}
      </Typography.Text>
      {skipped.length > 0 && (
        <Table<AssetBulkResult>
          size="small"
          rowKey="id"
          pagination={{ pageSize: 10, hideOnSinglePage: true }}
          dataSource={skipped}
          data-testid="asset-bulk-skipped"
          columns={[
            {
              key: 'asset',
              title: t('assets.bulk.result_asset'),
              render: (_: unknown, row: AssetBulkResult) => (
                <bdi dir="ltr">{row.tag ?? t('assets.bulk.unnamed')}</bdi>
              ),
            },
            {
              key: 'outcome',
              title: t('assets.bulk.result_outcome'),
              render: (_: unknown, row: AssetBulkResult) => t(`asset_bulk_outcome.${row.outcome}`),
            },
            {
              key: 'reason',
              title: t('assets.bulk.result_reason'),
              render: (_: unknown, row: AssetBulkResult) =>
                reasonText(t, row.code, row.field, row.params),
            },
          ]}
        />
      )}
    </Flex>
  );
}

/**
 * Change many assets at once (REQ-AST-051): edit a few shared fields, change the state, assign
 * them, or move them to the trash. The server runs it as a job, as you; an asset you may not
 * change is skipped with the reason, shown here as it happens.
 */
export function BulkActionsDialog({
  assetIds,
  open,
  onClose,
}: {
  assetIds: string[];
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const states = useAssetStates(open);
  const sites = useUnits('sites');
  const start = useStartAssetBulk();
  const [action, setAction] = useState<AssetBulkAction>('edit');
  const [location, setLocation] = useState('');
  const [costCentre, setCostCentre] = useState('');
  const [glCode, setGlCode] = useState('');
  const [siteId, setSiteId] = useState<string>();
  const [stateId, setStateId] = useState<string>();
  const [reason, setReason] = useState('');
  const [holderKind, setHolderKind] = useState<'none' | 'user' | 'department'>('none');
  const [holderId, setHolderId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string>();
  const [problem, setProblem] = useState<string | null>(null);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const changes = bulkChanges(action, {
    location,
    costCentre,
    glCode,
    siteId,
    stateId,
    reason,
    holderKind,
    holderId,
  });
  const close = () => {
    setJobId(undefined);
    setProblem(null);
    setKey(crypto.randomUUID());
    onClose();
  };
  const submit = () => {
    if (jobId !== undefined) {
      close();
      return;
    }
    if (changes === null) return;
    setProblem(null);
    start.mutate(
      { key, action, assetIds, changes },
      {
        onSuccess: (job) => {
          setJobId(job.id);
        },
        onError: (error) => {
          setProblem(problemText(t, error));
        },
      },
    );
  };
  return (
    <Modal
      open={open}
      title={t('assets.bulk.title')}
      cancelText={t('actions.cancel')}
      onCancel={close}
      footer={okFooter({
        okText: jobId === undefined ? t('assets.bulk.start') : t('assets.bulk.close'),
        onOk: submit,
        loading: start.isPending,
        danger: jobId === undefined && action === 'delete',
        cancel: jobId === undefined,
        whyDisabled:
          jobId === undefined && changes === null ? t('assets.bulk.need_change') : undefined,
        testId: 'asset-bulk-start',
      })}
      destroyOnHidden
      data-testid="asset-bulk-dialog"
    >
      {problem !== null && (
        <Alert type="error" showIcon message={problem} style={{ marginBottom: 12 }} />
      )}
      {jobId !== undefined ? (
        <>
          <Alert
            type="info"
            showIcon
            message={t('assets.bulk.started')}
            style={{ marginBottom: 12 }}
          />
          <BulkProgress jobId={jobId} />
        </>
      ) : (
        <Form layout="vertical" component="div">
          <Typography.Paragraph>
            {t('assets.bulk.selected', { total: assetIds.length })}
          </Typography.Paragraph>
          <Form.Item label={t('assets.bulk.action')}>
            <Radio.Group
              value={action}
              onChange={(event) => {
                setAction(event.target.value as AssetBulkAction);
              }}
              optionType="button"
              options={ACTIONS.map((a) => ({ value: a, label: t(`asset_bulk_action.${a}`) }))}
              data-testid="asset-bulk-action"
            />
          </Form.Item>
          {action === 'edit' && (
            <>
              <Typography.Paragraph type="secondary">
                {t('assets.bulk.edit_hint')}
              </Typography.Paragraph>
              <Form.Item label={t('assets.record.site_id')}>
                <Select
                  allowClear
                  value={siteId}
                  onChange={(value: string | undefined) => {
                    setSiteId(value);
                  }}
                  options={(sites.data ?? []).map((s) => ({ value: s.id, label: s.name }))}
                  data-testid="asset-bulk-site"
                />
              </Form.Item>
              <Form.Item label={t('assets.record.location')}>
                <Input
                  value={location}
                  count={lengthLimit(TEXT_MAX)}
                  onChange={(event) => {
                    setLocation(event.target.value);
                  }}
                  data-testid="asset-bulk-location"
                />
              </Form.Item>
              <Form.Item label={t('assets.record.cost_centre')}>
                <Input
                  value={costCentre}
                  count={lengthLimit(60)}
                  onChange={(event) => {
                    setCostCentre(event.target.value);
                  }}
                  data-testid="asset-bulk-cost-centre"
                />
              </Form.Item>
              <Form.Item label={t('assets.record.gl_code')}>
                <Input
                  value={glCode}
                  count={lengthLimit(40)}
                  onChange={(event) => {
                    setGlCode(event.target.value);
                  }}
                  data-testid="asset-bulk-gl-code"
                />
              </Form.Item>
            </>
          )}
          {action === 'move' && (
            <>
              <Form.Item label={t('assets.bulk.to_state')} required>
                <Select
                  value={stateId}
                  onChange={setStateId}
                  options={(states.data ?? []).map((s) => ({
                    value: s.id,
                    label: nameOf(s.names, locale),
                  }))}
                  data-testid="asset-bulk-state"
                />
              </Form.Item>
              <Form.Item label={t('assets.bulk.reason')}>
                <Input.TextArea
                  rows={2}
                  value={reason}
                  count={lengthLimit(500)}
                  onChange={(event) => {
                    setReason(event.target.value);
                  }}
                  data-testid="asset-bulk-reason"
                />
              </Form.Item>
            </>
          )}
          {action === 'assign' && (
            <>
              <Form.Item label={t('assets.bulk.holder_kind')}>
                <Radio.Group
                  value={holderKind}
                  onChange={(event) => {
                    setHolderKind(event.target.value as 'none' | 'user' | 'department');
                    setHolderId(null);
                  }}
                  options={[
                    { value: 'none', label: t('assets.bulk.holder_none') },
                    { value: 'user', label: t('assets.bulk.holder_user') },
                    { value: 'department', label: t('assets.bulk.holder_department') },
                  ]}
                  data-testid="asset-bulk-holder-kind"
                />
              </Form.Item>
              {holderKind !== 'none' && (
                <Form.Item label={t('assets.bulk.holder')} required>
                  {holderKind === 'user' ? (
                    <UserPicker
                      value={holderId}
                      onChange={setHolderId}
                      testId="asset-bulk-holder-user"
                      ariaLabel={t('assets.bulk.holder')}
                    />
                  ) : (
                    <DepartmentPicker
                      value={holderId}
                      onChange={setHolderId}
                      testId="asset-bulk-holder-department"
                      ariaLabel={t('assets.bulk.holder')}
                    />
                  )}
                </Form.Item>
              )}
            </>
          )}
          {action === 'delete' && (
            <Alert type="warning" showIcon message={t('assets.bulk.delete_hint')} />
          )}
        </Form>
      )}
    </Modal>
  );
}

const DAY_FIELDS = new Set(['acquired_on', 'warranty_expires_on', 'expires_on']);

/**
 * A preview value as words: IDs become the record's name (never an ID, rule d), dates the
 * person's format, money hidden without the right.
 */
function useMergeValue(names: {
  product: (id: string) => string;
  site: (id: string) => string;
  vendor: (id: string) => string;
}) {
  const t = useLabel();
  const dates = useDateTime();
  return (field: AssetMergeField, side: 'survivor' | 'merged'): string => {
    if (field.hidden) return t('assets.merge.hidden');
    const value: unknown = field[side];
    if (value === null || value === undefined || value === '') return t('assets.merge.empty');
    const text =
      typeof value === 'string'
        ? value
        : typeof value === 'number'
          ? String(value)
          : JSON.stringify(value);
    switch (field.field) {
      case 'product_id':
        return names.product(text);
      case 'site_id':
        return names.site(text);
      case 'vendor_id':
        return names.vendor(text);
      case 'purchase_order_id':
        return t('assets.merge.linked');
      default:
        return DAY_FIELDS.has(field.field) ? dates.formatDay(text) : text;
    }
  };
}

/**
 * Merge two duplicates (REQ-AST-052): the suggested survivor first (the discovered one, or the
 * newest scan), each field's two values side by side with a choice, and a swap. The server
 * checks assets.manage on both; the duplicate goes to the trash and its tag then finds the
 * asset kept.
 */
export function MergeDialog({
  ids,
  open,
  onClose,
}: {
  ids: [string, string] | undefined;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const navigate = useNavigate();
  const [swapped, setSwapped] = useState(false);
  const [first, second] = ids ?? [undefined, undefined];
  const preview = useAssetMergePreview(
    open ? (swapped ? second : first) : undefined,
    open ? (swapped ? first : second) : undefined,
  );
  const merge = useMergeAssets();
  const [choices, setChoices] = useState<Record<string, AssetMergeSide>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const data = preview.data;
  const survivorProduct = useAssetProduct(data?.survivor.product_id);
  const mergedProduct = useAssetProduct(data?.merged.product_id);
  const siteName = useSiteNames();
  const vendors = useVendors(false, open);
  const vendorNames = useMemo(
    () => new Map((vendors.data?.pages.flatMap((p) => p.items) ?? []).map((v) => [v.id, v.name])),
    [vendors.data],
  );
  const shown = useMergeValue({
    product: (id) =>
      [survivorProduct.data, mergedProduct.data].find((p) => p?.id === id)?.name ?? '',
    site: (id) => siteName(id),
    vendor: (id) => vendorNames.get(id) ?? '',
  });
  const loadProblem = preview.error === null ? null : problemText(t, preview.error);
  const sideOf = (field: AssetMergeField): AssetMergeSide => choices[field.field] ?? field.side;
  const fieldName = (name: string) => t(`assets.record.${name}`);
  const rows = useMemo(() => data?.fields ?? [], [data]);
  const close = () => {
    setChoices({});
    setProblem(null);
    setSwapped(false);
    setKey(crypto.randomUUID());
    onClose();
  };
  const submit = () => {
    if (data === undefined) return;
    setProblem(null);
    merge.mutate(
      {
        key,
        survivor: { id: data.survivor.id, version: data.survivor.version },
        merged: { id: data.merged.id, version: data.merged.version },
        choices,
      },
      {
        onSuccess: (result) => {
          close();
          void navigate(`/assets/${result.survivor.id}`);
        },
        onError: (error) => {
          setProblem(problemText(t, error));
        },
      },
    );
  };
  return (
    <Modal
      open={open}
      width={720}
      title={t('assets.merge.title')}
      cancelText={t('actions.cancel')}
      onCancel={close}
      footer={okFooter({
        okText: t('assets.merge.confirm'),
        onOk: submit,
        loading: merge.isPending,
        whyDisabled: data === undefined ? (loadProblem ?? t('assets.merge.choose_two')) : undefined,
        testId: 'asset-merge-confirm',
      })}
      destroyOnHidden
      data-testid="asset-merge-dialog"
    >
      {(problem ?? loadProblem) !== null && (
        <Alert
          type="error"
          showIcon
          message={problem ?? loadProblem}
          style={{ marginBottom: 12 }}
          data-testid="asset-merge-problem"
        />
      )}
      <Typography.Paragraph>{t('assets.merge.hint')}</Typography.Paragraph>
      {data !== undefined && (
        <Flex vertical gap={8}>
          <Flex gap={8} wrap align="center" justify="space-between">
            <Typography.Text type="secondary">{t('assets.merge.suggested')}</Typography.Text>
            <Button
              onClick={() => {
                setSwapped(!swapped);
                setChoices({});
              }}
              data-testid="asset-merge-swap"
            >
              {t('assets.merge.swap')}
            </Button>
          </Flex>
          <Table<AssetMergeField>
            size="small"
            rowKey="field"
            pagination={false}
            scroll={{ x: 'max-content' }}
            dataSource={rows}
            data-testid="asset-merge-fields"
            columns={[
              {
                key: 'field',
                title: t('assets.merge.field'),
                render: (_: unknown, f: AssetMergeField) => fieldName(f.field),
              },
              {
                key: 'survivor',
                title: (
                  <span>
                    {t('assets.merge.keep')}: <bdi dir="ltr">{data.survivor.tag ?? ''}</bdi>
                  </span>
                ),
                render: (_: unknown, f: AssetMergeField) => (
                  <Radio
                    checked={sideOf(f) === 'survivor'}
                    disabled={f.hidden}
                    onChange={() => {
                      setChoices({ ...choices, [f.field]: 'survivor' });
                    }}
                    data-testid={`asset-merge-${f.field}-survivor`}
                  >
                    <bdi dir="auto">{shown(f, 'survivor')}</bdi>
                  </Radio>
                ),
              },
              {
                key: 'merged',
                title: (
                  <span>
                    {t('assets.merge.duplicate')}: <bdi dir="ltr">{data.merged.tag ?? ''}</bdi>
                  </span>
                ),
                render: (_: unknown, f: AssetMergeField) => (
                  <Radio
                    checked={sideOf(f) === 'merged'}
                    disabled={f.hidden}
                    onChange={() => {
                      setChoices({ ...choices, [f.field]: 'merged' });
                    }}
                    data-testid={`asset-merge-${f.field}-merged`}
                  >
                    <bdi dir="auto">{shown(f, 'merged')}</bdi>
                  </Radio>
                ),
              },
            ]}
          />
        </Flex>
      )}
    </Modal>
  );
}
