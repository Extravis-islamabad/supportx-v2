import { CloseOutlined, LaptopOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Flex, Select, Tooltip, Typography } from 'antd';
import { useMemo, useState } from 'react';

import {
  useAssetPicker,
  useLinkAssets,
  useRecordAssets,
  useUnlinkAsset,
  type AssetBase,
  type PickedAsset,
  type RecordAsset,
} from '@supportx/api-client';
import { EmptyText, WriteButton, reportError, useLabel } from '@supportx/ui';

import { useDebounced, SEARCH_DELAY_MS } from '../../useDebounced';

/** How a picked asset reads: its tag and name, the person's own marked. */
function pickedLabel(t: ReturnType<typeof useLabel>, asset: PickedAsset): string {
  const name = [asset.tag, asset.name].filter(Boolean).join(' · ');
  return asset.mine ? t('assets.link.mine', { name }) : name;
}

/**
 * The asset picker of a form (REQ-AST-025): the person's own assets first (or `forUser`'s, for
 * staff raising for someone), then, for staff, a search by tag, serial or name.
 */
export function AssetPickerField({
  value,
  onChange,
  forUser,
  testId,
  id,
  ariaLabel,
}: {
  value: string[];
  onChange: (ids: string[]) => void;
  forUser: string | null;
  testId: string;
  id?: string;
  /** Its name when no form label names it (the record panel's add field). */
  ariaLabel?: string;
}) {
  const t = useLabel();
  const [search, setSearch] = useState('');
  const [opened, setOpened] = useState(false);
  const q = useDebounced(search.trim(), SEARCH_DELAY_MS);
  // Asked only once the list is opened: a form never loads assets nobody looks at.
  const picker = useAssetPicker(q, forUser, opened);
  const options = useMemo(
    () =>
      (picker.data ?? []).map((a) => ({
        value: a.id,
        label: pickedLabel(t, a),
        'aria-label': pickedLabel(t, a),
      })),
    [picker.data, t],
  );
  return (
    <Select
      id={id}
      mode="multiple"
      allowClear
      showSearch
      filterOption={false}
      value={value}
      onChange={onChange}
      onSearch={setSearch}
      onOpenChange={(open) => {
        if (open) setOpened(true);
      }}
      loading={picker.isFetching}
      placeholder={t('assets.link.placeholder')}
      notFoundContent={picker.isFetching ? undefined : t('assets.link.none_found')}
      options={options}
      maxCount={20}
      style={{ width: '100%' }}
      aria-label={ariaLabel}
      data-testid={testId}
    />
  );
}

function assetText(t: ReturnType<typeof useLabel>, link: RecordAsset): string {
  if (link.gone) return t('assets.link.gone');
  if (link.hidden) return t('assets.link.hidden');
  return [link.tag, link.name].filter(Boolean).join(' · ');
}

/**
 * A record's linked assets (REQ-AST-025), for its panel: each as the reader may see it (a
 * removed or hidden one says so, never named), live through the record channel, with link and
 * unlink for those who may edit the record.
 */
export function RecordAssets({
  base,
  recordId,
  canEdit,
  requesterId,
}: {
  base: AssetBase;
  recordId: string;
  canEdit: boolean;
  requesterId: string | null;
}) {
  const t = useLabel();
  const found = useRecordAssets(base, recordId);
  const link = useLinkAssets(base, recordId);
  const unlink = useUnlinkAsset(base, recordId);
  const [adding, setAdding] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const rows = found.data?.items ?? [];
  const linked = new Set(rows.map((r) => r.asset_id));
  const add = () => {
    const fresh = adding.filter((a) => !linked.has(a));
    if (fresh.length === 0) return;
    link.mutate(
      { assetIds: fresh, key: crypto.randomUUID() },
      {
        onSuccess: () => {
          setAdding([]);
        },
        onError: reportError,
      },
    );
  };
  return (
    <Flex vertical gap={8} data-testid={`${base}-assets`}>
      {!found.isPending && rows.length === 0 && <EmptyText>{t('assets.link.empty')}</EmptyText>}
      {rows.map((row) => (
        <Flex
          key={row.id}
          align="center"
          gap={8}
          data-testid={`record-asset-${row.asset_id}`}
          data-state={row.gone ? 'gone' : row.hidden ? 'hidden' : 'shown'}
        >
          <LaptopOutlined aria-hidden />
          <Typography.Text
            type={row.gone || row.hidden ? 'secondary' : undefined}
            ellipsis={{ tooltip: assetText(t, row) }}
            style={{ flex: 1, minWidth: 0 }}
          >
            <bdi>{assetText(t, row)}</bdi>
          </Typography.Text>
          {canEdit && (
            <Tooltip title={t('assets.link.remove', { name: assetText(t, row) })}>
              <Button
                type="text"
                size="small"
                icon={<CloseOutlined aria-hidden />}
                aria-label={t('assets.link.remove', { name: assetText(t, row) })}
                loading={unlink.isPending && unlink.variables.link.id === row.id}
                onClick={() => {
                  unlink.mutate({ link: row }, { onError: reportError });
                }}
                data-testid={`record-asset-remove-${row.asset_id}`}
              />
            </Tooltip>
          )}
        </Flex>
      ))}
      {/* A small link until someone links one (lane C, #357): no open picker on every record. */}
      {canEdit && !open && (
        <Button
          type="link"
          size="small"
          icon={<PlusOutlined aria-hidden />}
          style={{ paddingInline: 0, alignSelf: 'flex-start' }}
          onClick={() => {
            setOpen(true);
          }}
          data-testid={`${base}-assets-open`}
        >
          {t('assets.link.open')}
        </Button>
      )}
      {canEdit && open && (
        <Flex gap={8} align="start">
          <div style={{ flex: 1, minWidth: 0 }}>
            <AssetPickerField
              value={adding}
              onChange={setAdding}
              forUser={requesterId}
              testId={`${base}-assets-add`}
              ariaLabel={t('assets.link.open')}
            />
          </div>
          <WriteButton
            onClick={add}
            loading={link.isPending}
            disabled={adding.length === 0}
            whyDisabled={t('assets.link.choose_first')}
            data-testid={`${base}-assets-link`}
          >
            {t('assets.link.add')}
          </WriteButton>
        </Flex>
      )}
    </Flex>
  );
}
