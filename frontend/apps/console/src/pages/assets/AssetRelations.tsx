import {
  Alert,
  Button,
  Card,
  Flex,
  Form,
  List,
  Modal,
  Segmented,
  Select,
  Space,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';
import { Link } from 'react-router';

import {
  ApiError,
  useAssetComponents,
  useAssetHoldings,
  useAssetLinks,
  useAssetRecords,
  useAssetRelations,
  useStructure,
  useUser,
  type AssetLinkKind,
  type AssetRecord,
} from '@supportx/api-client';
import { EmptyText, reportError, useDateTime, useLabel, WriteButton } from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { DepartmentPicker, UserPicker } from '../incidents/pickers';
import { okFooter } from './dialogOk';

type HolderKind = 'user' | 'department' | 'asset';
const LINK_KINDS: AssetLinkKind[] = ['connected_to', 'depends_on', 'runs_on', 'backs_up'];

function problemText(t: ReturnType<typeof useLabel>, error: unknown): string | null {
  if (error instanceof ApiError && error.problem !== null) {
    const field = error.fieldErrors[0];
    if (field !== undefined) return t(`errors.field.${field.code}`, field.params ?? {});
    return t(error.messageKey, error.params);
  }
  reportError(error);
  return null;
}

/** A person's name (a deactivated or removed one still reads as a name, never an ID). */
function PersonName({ id }: { id: string }) {
  const t = useLabel();
  const user = useUser(id);
  return <bdi dir="auto">{user.data?.display_name ?? t('audit.ui.erased_person')}</bdi>;
}

function DepartmentName({ id }: { id: string }) {
  const departments = useStructure('departments');
  const found = (departments.data ?? []).find((d) => d.id === id) as { name?: string } | undefined;
  return <bdi dir="auto">{found?.name ?? ''}</bdi>;
}

/** Another asset, searched by tag, serial or name (the list's own search). */
function AssetPicker({
  value,
  onChange,
  exclude,
  testId,
  ariaLabel,
}: {
  value: string | undefined;
  onChange: (id: string | undefined) => void;
  exclude: string;
  testId: string;
  ariaLabel: string;
}) {
  const [search, setSearch] = useState('');
  const searched = useDebounced(search, 250);
  const found = useAssetRecords({ search: searched });
  const rows = (found.data?.pages.flatMap((p) => p.items) ?? []).filter((a) => a.id !== exclude);
  return (
    <Select
      showSearch
      allowClear
      filterOption={false}
      value={value}
      onSearch={setSearch}
      onChange={onChange}
      loading={found.isFetching}
      aria-label={ariaLabel}
      data-testid={testId}
      style={{ width: '100%' }}
      options={rows.map((a) => ({ value: a.id, label: `${a.tag ?? ''} ${a.name}`.trim() }))}
    />
  );
}

function Holder({ asset }: { asset: AssetRecord }) {
  const t = useLabel();
  if (asset.owner_user_id != null) return <PersonName id={asset.owner_user_id} />;
  if (asset.department_id != null) return <DepartmentName id={asset.department_id} />;
  if (asset.parent_asset_id != null) {
    return <Link to={`/assets/${asset.parent_asset_id}`}>{t('assets.holder.fitted_to_open')}</Link>;
  }
  return <Typography.Text type="secondary">{t('assets.holder.none')}</Typography.Text>;
}

/** Give the asset to a person, a department or another asset (REQ-AST-018), with If-Match. */
function HolderDialog({
  asset,
  open,
  onClose,
}: {
  asset: AssetRecord;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { setHolder } = useAssetRelations();
  const [kind, setKind] = useState<HolderKind>('user');
  const [target, setTarget] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const close = () => {
    setTarget(null);
    setProblem(null);
    onClose();
  };
  return (
    <Modal
      open={open}
      title={t('assets.holder.give_title', { name: asset.name })}
      cancelText={t('actions.cancel')}
      onCancel={close}
      footer={okFooter({
        okText: t('assets.holder.give'),
        loading: setHolder.isPending,
        whyDisabled: target === null ? t('assets.holder.who_needed') : undefined,
        onOk: () => {
          if (target === null) return;
          setHolder.mutate(
            { id: asset.id, version: asset.version, holder: { kind, id: target } },
            {
              onSuccess: close,
              onError: (error) => {
                setProblem(problemText(t, error));
              },
            },
          );
        },
      })}
      destroyOnHidden
      data-testid="asset-holder-dialog"
    >
      {problem !== null && (
        <Alert type="error" showIcon message={problem} style={{ marginBottom: 12 }} />
      )}
      <Form layout="vertical" component="div">
        <Form.Item label={t('assets.holder.kind')}>
          <Segmented<HolderKind>
            value={kind}
            onChange={(next) => {
              setKind(next);
              setTarget(null);
            }}
            options={(['user', 'department', 'asset'] as const).map((k) => ({
              value: k,
              label: t(`asset_holder_kind.${k}`),
            }))}
            data-testid="asset-holder-kind"
          />
        </Form.Item>
        <Form.Item label={t('assets.holder.who')} required>
          {kind === 'user' ? (
            <UserPicker
              value={target}
              onChange={setTarget}
              testId="asset-holder-user"
              ariaLabel={t('assets.holder.who')}
            />
          ) : kind === 'department' ? (
            <DepartmentPicker
              value={target}
              onChange={setTarget}
              testId="asset-holder-department"
              ariaLabel={t('assets.holder.who')}
            />
          ) : (
            <AssetPicker
              value={target ?? undefined}
              onChange={(id) => {
                setTarget(id ?? null);
              }}
              exclude={asset.id}
              testId="asset-holder-asset"
              ariaLabel={t('assets.holder.who')}
            />
          )}
        </Form.Item>
      </Form>
    </Modal>
  );
}

function LinkDialog({
  asset,
  open,
  onClose,
}: {
  asset: AssetRecord;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { addLink } = useAssetRelations();
  const [kind, setKind] = useState<AssetLinkKind>('connected_to');
  const [to, setTo] = useState<string>();
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [problem, setProblem] = useState<string | null>(null);
  const close = () => {
    setTo(undefined);
    setProblem(null);
    setKey(crypto.randomUUID());
    onClose();
  };
  return (
    <Modal
      open={open}
      title={t('assets.links.add_title', { name: asset.name })}
      cancelText={t('actions.cancel')}
      onCancel={close}
      footer={okFooter({
        okText: t('assets.links.add'),
        loading: addLink.isPending,
        whyDisabled: to === undefined ? t('assets.links.to_needed') : undefined,
        onOk: () => {
          if (to === undefined) return;
          addLink.mutate(
            { id: asset.id, to, kind, key },
            {
              onSuccess: close,
              onError: (error) => {
                setProblem(problemText(t, error));
              },
            },
          );
        },
      })}
      destroyOnHidden
      data-testid="asset-link-dialog"
    >
      {problem !== null && (
        <Alert type="error" showIcon message={problem} style={{ marginBottom: 12 }} />
      )}
      <Form layout="vertical" component="div">
        <Form.Item label={t('assets.links.kind')} required>
          <Select
            value={kind}
            onChange={setKind}
            data-testid="asset-link-kind"
            options={LINK_KINDS.map((k) => ({ value: k, label: t(`asset_link_kind.${k}`) }))}
          />
        </Form.Item>
        <Form.Item label={t('assets.links.to')} required>
          <AssetPicker
            value={to}
            onChange={setTo}
            exclude={asset.id}
            testId="asset-link-to"
            ariaLabel={t('assets.links.to')}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/**
 * Who holds the asset and who held it, what is fitted to it, and how it relates to others
 * (WP-049a s4; REQ-AST-018, 019, 026, 027). Every change refreshes live through the asset's
 * channel; links show from both ends with the wording for each side.
 */
export function AssetRelations({ asset, manage }: { asset: AssetRecord; manage: boolean }) {
  const t = useLabel();
  const { format } = useDateTime();
  const holdings = useAssetHoldings(asset.id);
  const links = useAssetLinks(asset.id);
  const components = useAssetComponents(asset.id);
  const { setHolder, removeLink } = useAssetRelations();
  const [dialog, setDialog] = useState<'holder' | 'link'>();
  const componentRows = useMemo(() => components.data?.items ?? [], [components.data]);
  return (
    <Flex vertical gap={16}>
      <Card
        title={t('assets.holder.title')}
        extra={
          manage && (
            <Space>
              <WriteButton
                onClick={() => {
                  setDialog('holder');
                }}
                data-testid="asset-holder-open"
              >
                {t('assets.holder.give')}
              </WriteButton>
              {holdings.data?.some((h) => h.ended_at === null) === true && (
                <Button
                  onClick={() => {
                    setHolder.mutate(
                      { id: asset.id, version: asset.version, holder: null },
                      { onError: reportError },
                    );
                  }}
                  data-testid="asset-holder-clear"
                >
                  {t('assets.holder.take_back')}
                </Button>
              )}
            </Space>
          )
        }
        data-testid="asset-holder"
      >
        <Typography.Paragraph>
          <Holder asset={asset} />
        </Typography.Paragraph>
        <List
          size="small"
          header={t('assets.holder.history')}
          dataSource={holdings.data ?? []}
          locale={{ emptyText: <EmptyText>{t('assets.holder.never')}</EmptyText> }}
          data-testid="asset-holdings"
          renderItem={(h) => (
            <List.Item key={`${h.holder_id}-${h.started_at}`}>
              <Space wrap>
                {h.holder_kind === 'user' ? (
                  <PersonName id={h.holder_id} />
                ) : h.holder_kind === 'department' ? (
                  <DepartmentName id={h.holder_id} />
                ) : (
                  <Link to={`/assets/${h.holder_id}`}>{t('assets.holder.fitted_to_open')}</Link>
                )}
                <Typography.Text type="secondary">
                  {h.ended_at === null
                    ? t('assets.holder.since', { from: format(h.started_at) })
                    : t('assets.holder.between', {
                        from: format(h.started_at),
                        to: format(h.ended_at),
                      })}
                </Typography.Text>
              </Space>
            </List.Item>
          )}
        />
      </Card>
      <Card title={t('assets.components.title')} data-testid="asset-components">
        <List
          size="small"
          dataSource={componentRows}
          locale={{ emptyText: <EmptyText>{t('assets.components.none')}</EmptyText> }}
          renderItem={(c) => (
            <List.Item key={c.id}>
              <Link to={`/assets/${c.id}`}>
                <bdi dir="ltr">{c.tag ?? ''}</bdi> <bdi dir="auto">{c.name}</bdi>
              </Link>
            </List.Item>
          )}
        />
      </Card>
      <Card
        title={t('assets.links.title')}
        extra={
          manage && (
            <WriteButton
              onClick={() => {
                setDialog('link');
              }}
              data-testid="asset-link-open"
            >
              {t('assets.links.add')}
            </WriteButton>
          )
        }
        data-testid="asset-links"
      >
        <List
          size="small"
          dataSource={links.data ?? []}
          locale={{ emptyText: <EmptyText>{t('assets.links.none')}</EmptyText> }}
          renderItem={(link) => (
            <List.Item
              key={link.id}
              actions={
                manage
                  ? [
                      <Button
                        key="remove"
                        size="small"
                        onClick={() => {
                          removeLink.mutate(
                            { id: asset.id, linkId: link.id },
                            { onError: reportError },
                          );
                        }}
                        data-testid={`asset-link-remove-${link.id}`}
                      >
                        {t('assets.links.remove')}
                      </Button>,
                    ]
                  : []
              }
            >
              <Space>
                <Typography.Text type="secondary">
                  {t(`${link.outgoing ? 'asset_link_kind' : 'asset_link_kind_in'}.${link.kind}`)}
                </Typography.Text>
                <Link to={`/assets/${link.other.id}`}>
                  <bdi dir="ltr">{link.other.tag ?? ''}</bdi>{' '}
                  <bdi dir="auto">{link.other.name}</bdi>
                </Link>
              </Space>
            </List.Item>
          )}
        />
      </Card>
      <HolderDialog
        asset={asset}
        open={dialog === 'holder'}
        onClose={() => {
          setDialog(undefined);
        }}
      />
      <LinkDialog
        asset={asset}
        open={dialog === 'link'}
        onClose={() => {
          setDialog(undefined);
        }}
      />
    </Flex>
  );
}
