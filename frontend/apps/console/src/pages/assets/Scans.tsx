import { Flex, Table, Typography } from 'antd';

import { useAssetScans, type AssetScan, type AssetScanChange } from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { loadedEmpty, ToneTag, useDateTime, useLabel } from '@supportx/ui';

// The asset's Scans tab (WP-049b s3; REQ-AST-054): each scan with its source and type, how it
// went (a failed one with its reason, AC3) and what it changed (AC1). Kept as long as the asset
// settings say; refreshed live when a scan arrives (the asset's channel, `fields`: scans).

function Change({ change }: { change: AssetScanChange }) {
  const t = useLabel();
  const list = useListFormat();
  const details = [change.model, change.capacity, change.version, change.publisher].filter(
    (v): v is string => v !== null && v !== undefined && v !== '',
  );
  return (
    <Typography.Text>
      {t(`asset_scan_change.${change.kind}`)}
      {change.category !== null && change.category !== undefined
        ? ` · ${t(`asset_hardware_category.${change.category}`)}`
        : ''}
      {': '}
      <bdi dir="auto">{change.name}</bdi>
      {details.length > 0 && (
        <>
          {' ('}
          <bdi dir="auto">{list(details)}</bdi>
          {')'}
        </>
      )}
    </Typography.Text>
  );
}

export function ScansTab({ assetId }: { assetId: string }) {
  const t = useLabel();
  const dates = useDateTime();
  const scans = useAssetScans(assetId);
  return (
    <Table<AssetScan>
      size="small"
      rowKey="id"
      pagination={false}
      loading={scans.isPending}
      dataSource={scans.data?.items ?? []}
      scroll={{ x: 'max-content' }}
      locale={{ emptyText: loadedEmpty(scans.isPending, t('assets.scans.none')) }}
      data-testid="asset-scans"
      columns={[
        {
          key: 'when',
          title: t('assets.scans.when'),
          render: (_, scan) => dates.format(scan.scanned_at),
        },
        {
          key: 'source',
          title: t('assets.scans.source'),
          render: (_, scan) =>
            scan.scan_type === null
              ? t(`asset_scan_source.${scan.source}`)
              : `${t(`asset_scan_source.${scan.source}`)} · ${t(`asset_scan_type.${scan.scan_type}`)}`,
        },
        {
          key: 'result',
          title: t('assets.scans.result'),
          render: (_, scan) => (
            <Flex vertical gap={2}>
              <ToneTag
                tone={scan.result === 'ok' ? 'success' : 'error'}
                testId={`scan-result-${scan.id}`}
              >
                {t(`asset_scan_result.${scan.result}`)}
              </ToneTag>
              {scan.failure_reason !== null && (
                <Typography.Text type="secondary" data-testid={`scan-reason-${scan.id}`}>
                  {t(`asset_scan_failure.${scan.failure_reason}`)}
                </Typography.Text>
              )}
            </Flex>
          ),
        },
        {
          key: 'changes',
          title: t('assets.scans.changes'),
          render: (_, scan) =>
            scan.changes.length === 0 ? (
              <Typography.Text type="secondary">{t('assets.scans.no_changes')}</Typography.Text>
            ) : (
              <Flex vertical gap={2} data-testid={`scan-changes-${scan.id}`}>
                {scan.changes.map((change, index) => (
                  <Change key={`${change.kind}-${String(index)}`} change={change} />
                ))}
              </Flex>
            ),
        },
      ]}
    />
  );
}
