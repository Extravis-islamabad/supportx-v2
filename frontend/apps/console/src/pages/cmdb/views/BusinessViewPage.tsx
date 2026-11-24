import { useQueryClient } from '@tanstack/react-query';
import { App, Flex, Form, Input, Modal, Result, Skeleton, Typography } from 'antd';
import { useCallback, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router';

import {
  queryKeys,
  useBusinessView,
  useCi,
  useDeleteBusinessView,
  useSaveBusinessViewAsNew,
  useUpdateBusinessView,
  type BusinessView,
} from '@supportx/api-client';
import type { MapPoint } from '@supportx/flow';
import { useRecordEvents } from '@supportx/realtime';
import {
  ConflictDialog,
  HeaderActions,
  NoAccess,
  NotInPlan,
  PageHeader,
  WriteButton,
  lengthLimit,
  reportError,
  useAccess,
  useConflict,
  useDateTime,
  useLabel,
  useLicence,
} from '@supportx/ui';

import { DESCRIPTION_MAX, NAME_MAX } from '../form';
import { MapWorkspace } from '../map/MapWorkspace';
import { positionsIn, positionsOut, textOrNull, type MapSettings } from '../map/positions';

/**
 * One business view (REQ-CMDB-009): its map opened with the saved layout, filters and pinned
 * positions, seen through the viewer's own rights (lane C's condition 4: a CI they may not open
 * is a placeholder, whoever saved the view). Save, save as new, rename and remove for its owner
 * or a CMDB administrator. Live through the view's own channel.
 */
export function BusinessViewPage() {
  const { viewId = '' } = useParams();
  const t = useLabel();
  const { can } = useAccess();
  const { has, isAdmin } = useLicence();
  const queryClient = useQueryClient();
  const found = useBusinessView(viewId);
  useRecordEvents(
    'cmdb_view',
    viewId,
    (message) => {
      if (message.covered === true) return; // a refresh: `covers` refetched the view
      void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.view(viewId) });
    },
    { covers: [queryKeys.cmdb.view(viewId)] },
  );
  if (!has('cmdb')) return <NotInPlan titleKey="cmdb.views.title" isAdmin={isAdmin} />;
  if (!can('cmdb.view')) return <NoAccess titleKey="cmdb.views.title" />;
  if (found.isPending) return <Skeleton active data-testid="cmdb-view-loading" />;
  if (found.isError)
    return <Result status="404" title={t('errors.cmdb_business_view_not_found')} />;
  return <ViewRecord key={found.data.id} view={found.data} />;
}

type Dialog = 'rename' | 'save-as-new' | null;

function ViewRecord({ view }: { view: BusinessView }) {
  const t = useLabel();
  const navigate = useNavigate();
  const { message, modal } = App.useApp();
  const dates = useDateTime();
  const base = useCi(view.base_ci_id);
  const update = useUpdateBusinessView();
  const remove = useDeleteBusinessView();
  const conflict = useConflict();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [opened, setOpened] = useState(view);
  const settings = useRef<MapSettings>({ layout: view.layout, filters: view.filters });
  const positions = useRef<ReadonlyMap<string, MapPoint>>(positionsIn(view.positions));
  // The map opens once with what was saved; later saves (ours or live) keep the map as it is.
  const [initial] = useState(() => ({
    layout: view.layout,
    filters: view.filters,
    positions: positionsIn(view.positions),
  }));
  const onSettings = useCallback((next: MapSettings) => {
    settings.current = next;
  }, []);
  const onPositions = useCallback((next: ReadonlyMap<string, MapPoint>) => {
    positions.current = next;
  }, []);
  const current = () => ({
    layout: settings.current.layout,
    filters: settings.current.filters,
    positions: positionsOut(positions.current),
  });

  const save = (version: number) => {
    update.mutate(
      { id: view.id, version, changes: current() },
      {
        onSuccess: (saved) => {
          setOpened(saved);
          void message.success(t('cmdb.views.saved'));
        },
        onError: (error) => {
          if (!conflict.take(error)) reportError(error);
        },
      },
    );
  };

  return (
    <Flex vertical gap={16} data-testid="cmdb-view">
      <PageHeader
        title={<bdi>{view.name}</bdi>}
        back={{
          label: t('cmdb.views.back'),
          onClick: () => void navigate('/cmdb/views'),
        }}
        description={
          <Flex vertical gap={2}>
            {view.description !== null && <bdi>{view.description}</bdi>}
            <Typography.Text type="secondary">
              {t('cmdb.views.meta', {
                base: base.data?.name ?? t('cmdb.map.restricted'),
                owner: view.owner_name ?? t('cmdb.views.no_owner'),
                at: dates.format(view.updated_at),
              })}
            </Typography.Text>
          </Flex>
        }
        extra={
          <HeaderActions
            primary={
              view.can_edit ? (
                <WriteButton
                  type="primary"
                  loading={update.isPending}
                  onClick={() => {
                    setOpened(view);
                    save(view.version);
                  }}
                  data-testid="cmdb-view-save"
                >
                  {t('actions.save')}
                </WriteButton>
              ) : undefined
            }
            more={[
              {
                key: 'save-as-new',
                label: t('cmdb.views.save_as_new'),
                testId: 'cmdb-view-save-as-new',
                onClick: () => {
                  setDialog('save-as-new');
                },
              },
              ...(view.can_edit
                ? [
                    {
                      key: 'rename',
                      label: t('cmdb.views.rename'),
                      testId: 'cmdb-view-rename',
                      onClick: () => {
                        setDialog('rename');
                      },
                    },
                  ]
                : []),
              ...(view.can_delete
                ? [
                    {
                      key: 'delete',
                      label: t('cmdb.views.delete'),
                      danger: true,
                      testId: 'cmdb-view-delete',
                      onClick: () => {
                        modal.confirm({
                          title: t('cmdb.views.delete_confirm', { name: view.name }),
                          okText: t('cmdb.views.delete'),
                          okButtonProps: { danger: true, 'data-testid': 'cmdb-view-delete-ok' },
                          cancelText: t('actions.cancel'),
                          onOk: () =>
                            remove.mutateAsync({ id: view.id, version: view.version }).then(() => {
                              void message.success(t('cmdb.views.deleted'));
                              void navigate('/cmdb/views');
                            }, reportError),
                        });
                      },
                    },
                  ]
                : []),
            ]}
          />
        }
      />
      <MapWorkspace
        baseId={view.base_ci_id}
        fileName={view.name}
        canEdit={false}
        initial={initial}
        onSettings={onSettings}
        onPositions={onPositions}
        testId="cmdb-view-map"
      />
      {dialog !== null && (
        <NameDialog
          view={view}
          mode={dialog}
          onClose={() => {
            setDialog(null);
          }}
          current={current}
        />
      )}
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        opened={opened}
        latest={view}
        fieldLabel={(field) => t(`cmdb.field.${field}`)}
        onReload={() => {
          conflict.clear();
          setOpened(view);
        }}
        onKeepMine={() => {
          const version = conflict.latestVersion ?? view.version;
          conflict.clear();
          save(version);
        }}
      />
    </Flex>
  );
}

/** Rename the view, or save the map as a new view you own (the first stays as it was). */
function NameDialog({
  view,
  mode,
  onClose,
  current,
}: {
  view: BusinessView;
  mode: 'rename' | 'save-as-new';
  onClose: () => void;
  current: () => Pick<BusinessView, 'layout' | 'filters'> & {
    positions: Record<string, { x: number; y: number }>;
  };
}) {
  const t = useLabel();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [form] = Form.useForm<{ name: string; description?: string }>();
  const [key] = useState(() => crypto.randomUUID());
  const update = useUpdateBusinessView();
  const copy = useSaveBusinessViewAsNew();
  const naming = mode === 'rename';
  return (
    <Modal
      open
      title={t(naming ? 'cmdb.views.rename' : 'cmdb.views.save_as_new')}
      onCancel={onClose}
      okText={t('actions.save')}
      cancelText={t('actions.cancel')}
      okButtonProps={{
        loading: update.isPending || copy.isPending,
        'data-testid': 'cmdb-view-name-ok',
      }}
      onOk={() => {
        form.submit();
      }}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          name: naming ? view.name : t('cmdb.views.copy_name', { name: view.name }),
          description: view.description ?? undefined,
        }}
        onFinish={(draft) => {
          const named = { name: draft.name.trim(), description: textOrNull(draft.description) };
          if (naming) {
            update.mutate(
              { id: view.id, version: view.version, changes: named },
              {
                onSuccess: () => {
                  void message.success(t('cmdb.views.saved'));
                  onClose();
                },
                onError: reportError,
              },
            );
            return;
          }
          copy.mutate(
            { id: view.id, key, changes: { ...current(), ...named } },
            {
              onSuccess: (made) => {
                void message.success(t('cmdb.views.saved_as_new'));
                onClose();
                void navigate(`/cmdb/views/${made.id}`);
              },
              onError: reportError,
            },
          );
        }}
      >
        <Form.Item
          name="name"
          label={t('cmdb.field.name')}
          rules={[{ required: true, whitespace: true, message: t('errors.field.required') }]}
        >
          <Input count={lengthLimit(NAME_MAX)} data-testid="cmdb-view-name" />
        </Form.Item>
        <Form.Item name="description" label={t('cmdb.field.description')}>
          <Input.TextArea
            count={lengthLimit(DESCRIPTION_MAX)}
            autoSize={{ minRows: 2, maxRows: 6 }}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
