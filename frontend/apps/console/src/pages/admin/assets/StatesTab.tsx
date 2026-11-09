import {
  Button,
  Card,
  Checkbox,
  Flex,
  Form,
  Modal,
  Popconfirm,
  Select,
  Table,
  Tag,
  Typography,
} from 'antd';
import { useState } from 'react';

import type { AssetState, AssetStateCategory } from '@supportx/api-client';
import { useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { LabelsFields, Problems } from '../incidents/shared';
import { codeFrom, nameOf, useCatalogueSave, type Names } from './shared';

const STATE_CATEGORIES: AssetStateCategory[] = [
  'in_stock',
  'in_use',
  'in_repair',
  'retired',
  'disposed',
];

interface Draft {
  names: Names;
  category: AssetStateCategory;
  reasonRequired: boolean;
  isDefault: boolean;
}

/**
 * Asset states: each belongs to a fixed category (what reports and the automatic moves go by).
 * One state per category is its default. States used by loans or disposal (system) and the
 * defaults can be renamed but not deleted; a state in use is refused with how often it is used.
 */
export function StatesTab({ states }: { states: AssetState[] }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { run, problems, clear, pending } = useCatalogueSave();
  // null: closed; 'new': adding; otherwise the state being edited.
  const [editing, setEditing] = useState<AssetState | 'new' | null>(null);
  const [draft, setDraft] = useState<Draft>();
  const [key, setKey] = useState(() => crypto.randomUUID());
  const open = (state: AssetState | 'new') => {
    clear();
    setKey(crypto.randomUUID());
    setEditing(state);
    setDraft(
      state === 'new'
        ? { names: {}, category: 'in_stock', reasonRequired: false, isDefault: false }
        : {
            names: state.names,
            category: state.category,
            reasonRequired: state.reason_required,
            isDefault: state.is_default_for_category,
          },
    );
  };
  const close = () => {
    clear();
    setEditing(null);
  };
  const save = () => {
    if (draft === undefined || editing === null) return;
    if (editing === 'new') {
      run(
        {
          kind: 'create_state',
          key,
          body: {
            code: codeFrom(draft.names.en ?? '', new Set(states.map((s) => s.code)), 'state'),
            names: draft.names,
            category: draft.category,
            reason_required: draft.reasonRequired,
            is_default_for_category: draft.isDefault,
          },
        },
        close,
      );
      return;
    }
    run(
      {
        kind: 'state',
        id: editing.id,
        version: editing.version,
        body: {
          names: draft.names,
          // A system state's category is what loans and disposal rely on: never sent.
          ...(!editing.system && { category: draft.category }),
          reason_required: draft.reasonRequired,
          is_default_for_category: draft.isDefault,
        },
      },
      close,
      close,
    );
  };
  return (
    <Card
      title={t('assets.admin.states')}
      extra={
        <WriteButton
          onClick={() => {
            open('new');
          }}
          data-testid="asset-state-add"
        >
          {t('actions.add')}
        </WriteButton>
      }
      data-testid="asset-states"
    >
      <Typography.Paragraph type="secondary">{t('assets.admin.states_help')}</Typography.Paragraph>
      {editing === null && <Problems problems={problems} testId="asset-states-problems" />}
      <Table
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={states}
        columns={[
          {
            key: 'name',
            title: t('settings.name'),
            render: (_: unknown, state: AssetState) => (
              <Flex gap={8} align="center" wrap>
                <bdi dir="auto" data-testid={`asset-state-name-${state.code}`}>
                  {nameOf(state.names, locale)}
                </bdi>
                {state.is_default_for_category && <Tag>{t('assets.admin.default')}</Tag>}
                {state.system && <Tag>{t('assets.admin.system')}</Tag>}
              </Flex>
            ),
          },
          {
            key: 'category',
            title: t('assets.admin.category'),
            render: (_: unknown, state: AssetState) => t(`asset_state_category.${state.category}`),
          },
          {
            key: 'reason',
            title: t('assets.admin.reason_required'),
            render: (_: unknown, state: AssetState) =>
              state.reason_required ? t('assets.admin.yes') : t('assets.admin.no'),
          },
          {
            key: 'actions',
            title: <span className="sr-only">{t('assets.admin.actions')}</span>,
            render: (_: unknown, state: AssetState) => (
              <Flex gap={4} justify="end">
                <Button
                  type="link"
                  onClick={() => {
                    open(state);
                  }}
                  data-testid={`asset-state-edit-${state.code}`}
                >
                  {t('actions.edit')}
                </Button>
                {!state.system && !state.is_default_for_category && (
                  <Popconfirm
                    title={t('assets.admin.delete_confirm', { name: nameOf(state.names, locale) })}
                    okText={t('actions.delete')}
                    cancelText={t('actions.cancel')}
                    onConfirm={() => {
                      run({ kind: 'delete_state', id: state.id, version: state.version });
                    }}
                  >
                    <Button type="link" danger data-testid={`asset-state-delete-${state.code}`}>
                      {t('actions.delete')}
                    </Button>
                  </Popconfirm>
                )}
              </Flex>
            ),
          },
        ]}
      />
      <Modal
        open={editing !== null}
        title={editing === 'new' ? t('assets.admin.add_state') : t('assets.admin.edit_state')}
        okText={t('actions.save')}
        cancelText={t('actions.cancel')}
        onOk={save}
        onCancel={close}
        confirmLoading={pending}
        destroyOnHidden
        data-testid="asset-state-dialog"
      >
        {draft !== undefined && editing !== null && (
          <Form layout="vertical">
            <Problems problems={problems} testId="asset-state-problems" />
            <LabelsFields
              value={draft.names}
              onChange={(names) => {
                setDraft({ ...draft, names });
              }}
              testId="asset-state-name"
            />
            <Form.Item label={t('assets.admin.category')} htmlFor="asset-state-category">
              <Select
                id="asset-state-category"
                aria-label={t('assets.admin.category')}
                disabled={editing !== 'new' && editing.system}
                value={draft.category}
                onChange={(category: AssetStateCategory) => {
                  setDraft({ ...draft, category });
                }}
                options={STATE_CATEGORIES.map((code) => ({
                  value: code,
                  label: t(`asset_state_category.${code}`),
                }))}
                data-testid="asset-state-category"
              />
            </Form.Item>
            <Checkbox
              checked={draft.reasonRequired}
              onChange={(event) => {
                setDraft({ ...draft, reasonRequired: event.target.checked });
              }}
              data-testid="asset-state-reason"
            >
              {t('assets.admin.reason_required_help')}
            </Checkbox>
            <br />
            <Checkbox
              checked={draft.isDefault}
              onChange={(event) => {
                setDraft({ ...draft, isDefault: event.target.checked });
              }}
              data-testid="asset-state-default"
            >
              {t('assets.admin.default_for_category')}
            </Checkbox>
          </Form>
        )}
      </Modal>
    </Card>
  );
}
