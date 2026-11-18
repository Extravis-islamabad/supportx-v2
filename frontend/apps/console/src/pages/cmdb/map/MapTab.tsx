import { PlusOutlined, SaveOutlined } from '@ant-design/icons';
import { App, Flex, Form, Input, List, Modal, Typography } from 'antd';
import { useCallback, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  useBusinessViews,
  useCreateBusinessView,
  type BusinessViewFilters,
  type Ci,
} from '@supportx/api-client';
import type { CiMapLayout, MapPoint } from '@supportx/flow';
import { WriteButton, lengthLimit, reportError, useLabel } from '@supportx/ui';

import { DESCRIPTION_MAX, NAME_MAX } from '../form';
import { useCmdbRight } from '../rights';
import { AddRelationship } from './AddRelationship';
import { MapWorkspace } from './MapWorkspace';
import { DEFAULT_FILTERS, positionsOut, textOrNull, type MapSettings } from './positions';

/**
 * The CI's Map tab (template A; REQ-CMDB-007, 008): its relationships drawn, with add,
 * remove, expand, the filters and the exports, and the business views built on it.
 */
export function MapTab({ ci }: { ci: Ci }) {
  const t = useLabel();
  const may = useCmdbRight();
  const [adding, setAdding] = useState(false);
  // The map as it was when "Save as business view" was pressed.
  const [saving, setSaving] = useState<
    (MapSettings & { positions: ReadonlyMap<string, MapPoint> }) | null
  >(null);
  const settings = useRef<MapSettings>({ layout: 'radial', filters: DEFAULT_FILTERS });
  const positions = useRef<ReadonlyMap<string, MapPoint>>(new Map());
  const onSettings = useCallback((next: MapSettings) => {
    settings.current = next;
  }, []);
  const onPositions = useCallback((next: ReadonlyMap<string, MapPoint>) => {
    positions.current = next;
  }, []);
  return (
    <Flex vertical gap={16} data-testid="ci-map-tab">
      <MapWorkspace
        baseId={ci.id}
        fileName={ci.display_id}
        canEdit={ci.can_edit}
        onSettings={onSettings}
        onPositions={onPositions}
        actions={
          <>
            {ci.can_edit && (
              <WriteButton
                icon={<PlusOutlined />}
                onClick={() => {
                  setAdding(true);
                }}
                data-testid="ci-relationship-add"
              >
                {t('cmdb.map.add_relationship')}
              </WriteButton>
            )}
            {may('edit') && (
              <WriteButton
                icon={<SaveOutlined />}
                onClick={() => {
                  setSaving({ ...settings.current, positions: positions.current });
                }}
                data-testid="ci-map-save-view"
              >
                {t('cmdb.views.save_as_view')}
              </WriteButton>
            )}
          </>
        }
      />
      <ViewsOnCi ciId={ci.id} />
      {adding && (
        <AddRelationship
          ci={ci}
          onClose={() => {
            setAdding(false);
          }}
        />
      )}
      {saving !== null && (
        <SaveView
          ciId={ci.id}
          layout={saving.layout}
          filters={saving.filters}
          positions={saving.positions}
          onClose={() => {
            setSaving(null);
          }}
        />
      )}
    </Flex>
  );
}

/** Business views whose base is this CI (live through the views list). */
function ViewsOnCi({ ciId }: { ciId: string }) {
  const t = useLabel();
  const views = useBusinessViews({ baseCiId: ciId });
  const items = views.data?.pages.flatMap((p) => p.items) ?? [];
  if (items.length === 0) return null;
  return (
    <List
      size="small"
      header={t('cmdb.views.on_this_ci')}
      dataSource={items}
      data-testid="ci-map-views"
      renderItem={(view) => (
        <List.Item>
          <Link to={`/cmdb/views/${view.id}`}>
            <bdi>{view.name}</bdi>
          </Link>
          {view.description !== null && (
            <Typography.Text type="secondary" ellipsis style={{ maxWidth: '50%' }}>
              <bdi>{view.description}</bdi>
            </Typography.Text>
          )}
        </List.Item>
      )}
    />
  );
}

/** Save the map as it is now as a business view you own (REQ-CMDB-009). */
function SaveView({
  ciId,
  layout,
  filters,
  positions,
  onClose,
}: {
  ciId: string;
  layout: CiMapLayout;
  filters: BusinessViewFilters;
  positions: ReadonlyMap<string, MapPoint>;
  onClose: () => void;
}) {
  const t = useLabel();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [form] = Form.useForm<{ name: string; description?: string }>();
  const [key] = useState(() => crypto.randomUUID());
  const create = useCreateBusinessView();
  return (
    <Modal
      open
      title={t('cmdb.views.save_as_view')}
      onCancel={onClose}
      okText={t('actions.save')}
      cancelText={t('actions.cancel')}
      okButtonProps={{ loading: create.isPending, 'data-testid': 'ci-view-save' }}
      onOk={() => {
        form.submit();
      }}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={(draft) => {
          create.mutate(
            {
              key,
              body: {
                base_ci_id: ciId,
                name: draft.name.trim(),
                description: textOrNull(draft.description),
                layout,
                filters,
                positions: positionsOut(positions),
              },
            },
            {
              onSuccess: (made) => {
                void message.success(t('cmdb.views.saved'));
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
          <Input count={lengthLimit(NAME_MAX)} data-testid="ci-view-name" />
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
