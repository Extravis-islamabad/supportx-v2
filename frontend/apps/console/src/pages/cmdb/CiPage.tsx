import { useQueryClient } from '@tanstack/react-query';
import { App, Button, Flex, List, Modal, Result, TreeSelect, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router';

import {
  queryKeys,
  useChangeCiType,
  useCi,
  useCiHistory,
  useCiStates,
  useCiTypes,
  useCopyCi,
  useDeleteCi,
  usePreviewCiTypeChange,
  useUpdateCi,
  type Ci,
} from '@supportx/api-client';
import { applyServerErrors, useForm, zodResolver } from '@supportx/forms';
import { useListFormat } from '@supportx/labels';
import { useRecordChannel } from '@supportx/realtime';
import {
  HeaderActions,
  NoAccess,
  PropertiesPanel,
  PropertyList,
  RecordHeader,
  RecordPage,
  WriteButton,
  reportError,
  useAccess,
  useAppearance,
  useLabel,
} from '@supportx/ui';

import { useCmdbRight } from './rights';
import { CiFields } from './CiForm';
import { FIELDS, patchOf, schema, valuesOf, type Values } from './form';
import { nameOf, typeTree } from './names';

/** One configuration item (template A, D-147): live, edited in place, with its history. */
export function CiPage() {
  const { id = '' } = useParams();
  const t = useLabel();
  const { can } = useAccess();
  const found = useCi(id);
  const queryClient = useQueryClient();
  useRecordChannel('ci', id, () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.detail(id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.history(id) });
  });
  if (!can('cmdb.view')) return <NoAccess titleKey="nav.cmdb" />;
  if (found.isPending) return null;
  if (found.isError) return <Result status="404" title={t('errors.cmdb_ci_not_found')} />;
  return <CiRecord ci={found.data} key={found.data.version} />;
}

function CiRecord({ ci }: { ci: Ci }) {
  const t = useLabel();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const { locale, intlLocale } = useAppearance();
  const may = useCmdbRight();
  const types = useCiTypes();
  const states = useCiStates();
  const [editing, setEditing] = useState(false);
  const [moving, setMoving] = useState(false);
  const update = useUpdateCi(ci.id);
  const copy = useCopyCi(ci.id);
  const remove = useDeleteCi(ci.id);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: valuesOf(ci) });
  const typeOf = types.data?.items.find((x) => x.id === ci.type_id);
  const stateOf = states.data?.items.find((x) => x.id === ci.state_id);
  const dateFormat = new Intl.DateTimeFormat(intlLocale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });

  const save = form.handleSubmit((values) => {
    const changes = patchOf(values);
    update.mutate(
      { changes, version: ci.version },
      {
        onSuccess: () => {
          setEditing(false);
        },
        onError: (error) => {
          if (!applyServerErrors(error, form.setError, FIELDS)) reportError(error);
        },
      },
    );
  });

  const attributeValue = (key: string) => {
    const value = ci.custom[key];
    if (value === undefined || value === null) return '';
    if (typeof value === 'boolean') return t(value ? 'cmdb.yes' : 'cmdb.no');
    if (typeof value === 'string' || typeof value === 'number') return String(value);
    return JSON.stringify(value);
  };

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
          primary={
            ci.can_edit && !editing ? (
              <WriteButton
                type="primary"
                onClick={() => {
                  setEditing(true);
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
                        onSuccess: (made) => void navigate(`/cmdb/${made.id}`),
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
            ...(ci.can_delete
              ? [
                  {
                    key: 'delete',
                    label: t('cmdb.action.delete'),
                    danger: true,
                    testId: 'ci-delete',
                    onClick: () => {
                      remove.mutate(ci.version, {
                        onSuccess: () => {
                          void message.success(t('cmdb.action.delete'));
                          void navigate('/cmdb');
                        },
                        onError: reportError,
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
              title: t('cmdb.field.attributes'),
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
                    ...ci.attributes.map((a) => ({
                      key: `custom.${a.key}`,
                      label: a.names[locale] ?? a.names.en,
                      content: <bdi>{attributeValue(a.key)}</bdi>,
                      filled: attributeValue(a.key) !== '',
                    })),
                    {
                      key: 'updated',
                      label: t('cmdb.field.updated_at'),
                      content: dateFormat.format(new Date(ci.updated_at)),
                      filled: true,
                    },
                  ]}
                />
              ),
            },
          ]}
        />
      }
    >
      {editing ? (
        <Flex vertical gap={16}>
          <CiFields form={form} typeLocked />
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
              onClick={() => void save()}
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
          <CiHistory id={ci.id} />
        </Flex>
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

/** Move the CI to another type, showing first the values it would lose (REQ-CMDB-003). */
function ChangeType({ ci, onClose }: { ci: Ci; onClose: () => void }) {
  const t = useLabel();
  const list = useListFormat();
  const { locale } = useAppearance();
  const types = useCiTypes();
  const preview = usePreviewCiTypeChange(ci.id);
  const change = useChangeCiType(ci.id);
  const [typeId, setTypeId] = useState<string>();
  const tree = useMemo(
    () => typeTree(types.data?.items ?? [], (x) => nameOf(t, locale, x, 'cmdb_ci_type')),
    [types.data, t, locale],
  );
  const lost = preview.data?.lost ?? [];
  return (
    <Modal
      open
      title={t('cmdb.action.change_type')}
      onCancel={onClose}
      okText={t('cmdb.action.change_type')}
      okButtonProps={{
        disabled: typeId === undefined || preview.isPending,
        loading: change.isPending,
      }}
      onOk={() => {
        if (typeId === undefined) return;
        change.mutate(
          { typeId, version: ci.version },
          { onSuccess: onClose, onError: reportError },
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
            preview.mutate(next);
          }}
          treeData={tree}
          data-testid="ci-new-type"
        />
        {preview.data !== undefined && (
          <Typography.Text type={lost.length > 0 ? 'warning' : 'secondary'} data-testid="ci-lost">
            {lost.length > 0
              ? t('cmdb.change_type.lost', {
                  keys: list(
                    lost.map((key) => {
                      const a = ci.attributes.find((x) => x.key === key);
                      return a === undefined ? key : (a.names[locale] ?? a.names.en ?? key);
                    }),
                  ),
                })
              : t('cmdb.change_type.nothing_lost')}
          </Typography.Text>
        )}
      </Flex>
    </Modal>
  );
}

function CiHistory({ id }: { id: string }) {
  const t = useLabel();
  const list = useListFormat();
  const { intlLocale } = useAppearance();
  const history = useCiHistory(id);
  const entries = history.data?.pages.flatMap((p) => p.items) ?? [];
  const when = new Intl.DateTimeFormat(intlLocale, { dateStyle: 'medium', timeStyle: 'short' });
  return (
    <List
      data-testid="ci-history"
      header={t('cmdb.history')}
      dataSource={entries}
      renderItem={(entry) => (
        <List.Item>
          <Typography.Text>
            {t(`change_kind.${entry.kind}`)} ·{' '}
            {entry.actor_name ?? t(`actor_type.${entry.actor_type}`)} ·{' '}
            {when.format(new Date(entry.occurred_at))}
            {entry.changes.length > 0 &&
              ` · ${list(
                entry.changes.map((c) =>
                  c.field.startsWith('custom')
                    ? t('cmdb.field.attributes')
                    : t(`cmdb.field.${c.field}`),
                ),
              )}`}
          </Typography.Text>
        </List.Item>
      )}
    />
  );
}
