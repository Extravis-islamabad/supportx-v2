import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Flex,
  Form,
  Input,
  List,
  Modal,
  Segmented,
  Select,
  Space,
  Typography,
} from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  ApiError,
  queryKeys,
  useAssetGroupAssets,
  useAssetGroups,
  useAssetRelations,
  useAssetStates,
  type AssetGroup,
} from '@supportx/api-client';
import { useListChannel, useTenantChannel } from '@supportx/realtime';
import {
  EmptyText,
  lengthLimit,
  NoAccess,
  ListPage,
  PageHeader,
  pickerFormat,
  reportError,
  ToneTag,
  useAccess,
  useAppearance,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { nameOf } from '../admin/assets/shared';
import { okFooter } from './dialogOk';

// A dynamic group's condition: one field the people asking for groups use most (REQ-AST-028).
type Rule = { field: 'state_id'; value: string } | { field: 'warranty_expires_on'; value: string };

/** The end of this quarter (dayjs's quarter unit needs a plugin we don't load). */
function endOfQuarter(): Dayjs {
  const now = dayjs();
  return now.month(Math.floor(now.month() / 3) * 3 + 2).endOf('month');
}

function NewGroupDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useLabel();
  const { locale, dates } = useAppearance();
  const states = useAssetStates(open);
  const { createGroup } = useAssetRelations();
  const [name, setName] = useState('');
  const [kind, setKind] = useState<'static' | 'dynamic'>('static');
  const [field, setField] = useState<Rule['field']>('state_id');
  const [state, setState] = useState<string>();
  const [until, setUntil] = useState<Dayjs | null>(endOfQuarter());
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [problem, setProblem] = useState<string | null>(null);
  const close = () => {
    setName('');
    setProblem(null);
    setKey(crypto.randomUUID());
    onClose();
  };
  const filter =
    kind === 'static'
      ? null
      : field === 'state_id'
        ? state === undefined
          ? undefined
          : { field: 'state_id', op: 'eq', value: state }
        : until === null
          ? undefined
          : { field: 'warranty_expires_on', op: 'lte', value: until.format('YYYY-MM-DD') };
  const ready = name.trim() !== '' && filter !== undefined;
  return (
    <Modal
      open={open}
      title={t('assets.groups.new')}
      cancelText={t('actions.cancel')}
      onCancel={close}
      footer={okFooter({
        okText: t('assets.groups.add'),
        loading: createGroup.isPending,
        whyDisabled:
          name.trim() === ''
            ? t('assets.groups.name_needed')
            : filter === undefined
              ? t('assets.groups.rule_needed')
              : undefined,
        onOk: () => {
          if (!ready) return;
          createGroup.mutate(
            { key, body: { name: name.trim(), kind, filter } },
            {
              onSuccess: close,
              onError: (error) => {
                if (error instanceof ApiError && error.problem !== null)
                  setProblem(t(error.messageKey, error.params));
                else reportError(error);
              },
            },
          );
        },
      })}
      destroyOnHidden
      data-testid="asset-group-new"
    >
      {problem !== null && (
        <Alert type="error" showIcon message={problem} style={{ marginBottom: 12 }} />
      )}
      <Form layout="vertical" component="div">
        <Form.Item label={t('assets.groups.name')} required>
          <Input
            dir="auto"
            count={lengthLimit(200)}
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
            data-testid="asset-group-name"
          />
        </Form.Item>
        <Form.Item label={t('assets.groups.kind')}>
          <Segmented<'static' | 'dynamic'>
            value={kind}
            onChange={setKind}
            options={(['static', 'dynamic'] as const).map((k) => ({
              value: k,
              label: t(`asset_group_kind.${k}`),
            }))}
            data-testid="asset-group-kind"
          />
        </Form.Item>
        <Typography.Paragraph type="secondary">
          {t(`assets.groups.help_${kind}`)}
        </Typography.Paragraph>
        {kind === 'dynamic' && (
          <Space wrap>
            <Select<Rule['field']>
              value={field}
              onChange={setField}
              aria-label={t('assets.groups.rule')}
              style={{ minWidth: 200 }}
              options={[
                { value: 'state_id', label: t('assets.groups.rule_state') },
                { value: 'warranty_expires_on', label: t('assets.groups.rule_warranty') },
              ]}
              data-testid="asset-group-rule"
            />
            {field === 'state_id' ? (
              <Select
                value={state}
                onChange={setState}
                aria-label={t('assets.record.state')}
                style={{ minWidth: 180 }}
                options={(states.data ?? []).map((s) => ({
                  value: s.id,
                  label: nameOf(s.names, locale),
                }))}
                data-testid="asset-group-state"
              />
            ) : (
              <DatePicker
                value={until}
                onChange={setUntil}
                format={pickerFormat(dates, false)}
                aria-label={t('assets.groups.rule_warranty')}
              />
            )}
          </Space>
        )}
      </Form>
    </Modal>
  );
}

function GroupAssets({ group }: { group: AssetGroup }) {
  const t = useLabel();
  const assets = useAssetGroupAssets(group.id);
  return (
    <List
      size="small"
      loading={assets.isPending}
      dataSource={assets.data ?? []}
      locale={{ emptyText: <EmptyText>{t('assets.groups.empty')}</EmptyText> }}
      renderItem={(a) => (
        <List.Item key={a.id}>
          <Link to={`/assets/${a.id}`}>
            <bdi dir="ltr">{a.tag ?? ''}</bdi> <bdi dir="auto">{a.name}</bdi>
          </Link>
        </List.Item>
      )}
    />
  );
}

/**
 * Asset groups (WP-049a s4; REQ-AST-028): static ones are filled from the asset list's
 * selection; dynamic ones follow their condition, so an asset that comes to match is in at once.
 * Counts and lists refresh live (group events, and the asset list's own events).
 */
export function GroupsPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const access = useAccess();
  const queryClient = useQueryClient();
  const allowed = access.can('assets.view');
  const groups = useAssetGroups(allowed);
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<string>();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.assets.groups });
  useTenantChannel((event) => {
    if (event.type === 'assets.groups_changed') refresh();
  });
  // A changed asset can enter or leave a dynamic group: counts follow the asset list's events.
  useListChannel(allowed ? 'assets' : null, refresh);
  if (!allowed) return <NoAccess titleKey="nav.assets" />;
  return (
    <ListPage
      testId="asset-groups-page"
      header={
        <PageHeader
          title={t('assets.groups.title')}
          back={{ label: t('nav.assets'), onClick: () => void navigate('/assets') }}
          count={groups.data === undefined ? undefined : String(groups.data.length)}
          extra={
            access.can('assets.manage') && (
              <WriteButton
                type="primary"
                onClick={() => {
                  setAdding(true);
                }}
                data-testid="asset-group-new-open"
              >
                {t('assets.groups.new')}
              </WriteButton>
            )
          }
        />
      }
    >
      <Card data-testid="asset-groups">
        <List
          loading={groups.isPending}
          dataSource={groups.data ?? []}
          locale={{ emptyText: <EmptyText>{t('assets.groups.none')}</EmptyText> }}
          renderItem={(g) => (
            <List.Item key={g.id} data-testid={`asset-group-${g.id}`}>
              <Flex vertical style={{ width: '100%' }}>
                <Space wrap>
                  <Button
                    type="link"
                    style={{ padding: 0 }}
                    aria-expanded={open === g.id}
                    onClick={() => {
                      setOpen(open === g.id ? undefined : g.id);
                    }}
                    data-testid={`asset-group-toggle-${g.id}`}
                  >
                    <bdi dir="auto">{g.name}</bdi>
                  </Button>
                  <ToneTag tone="default">{t(`asset_group_kind.${g.kind}`)}</ToneTag>
                  <Typography.Text type="secondary">
                    {t('assets.groups.count', { count: g.count })}
                  </Typography.Text>
                </Space>
                {open === g.id && <GroupAssets group={g} />}
              </Flex>
            </List.Item>
          )}
        />
      </Card>
      <NewGroupDialog
        open={adding}
        onClose={() => {
          setAdding(false);
        }}
      />
    </ListPage>
  );
}
