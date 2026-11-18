import { App, Form, Modal, Radio, Select } from 'antd';
import { useState } from 'react';

import {
  useAddRelationships,
  useCiPicker,
  useRelationshipTypes,
  type Ci,
  type RelationshipDirection,
} from '@supportx/api-client';
import { reportError, useAppearance, useLabel } from '@supportx/ui';

import { SEARCH_DELAY_MS, useDebounced } from '../../../useDebounced';
import { relationshipName, relationshipTypeName } from './words';

/** Targets in one add, all or nothing (the API's limit). */
export const TARGETS_MAX = 50;

interface Draft {
  type_id?: string;
  direction: RelationshipDirection;
  targets: string[];
}

/**
 * Link this CI to up to 50 others with one relationship type (REQ-CMDB-007): the types this
 * CI's type may use come first (suggested ones on top), the targets through the CI picker. The
 * server checks the type's rules and edit rights on every CI; a refusal names the CI.
 */
export function AddRelationship({ ci, onClose }: { ci: Ci; onClose: () => void }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const [form] = Form.useForm<Draft>();
  const [key] = useState(() => crypto.randomUUID());
  const [search, setSearch] = useState('');
  const typed = useDebounced(search, SEARCH_DELAY_MS);
  const types = useRelationshipTypes(ci.type_id);
  const picker = useCiPicker(typed);
  const add = useAddRelationships(ci.id);
  const typeId = Form.useWatch('type_id', form);
  const chosen = types.data?.items.find((x) => x.id === typeId);

  const submit = (draft: Draft) => {
    if (draft.type_id === undefined) return;
    add.mutate(
      { typeId: draft.type_id, direction: draft.direction, targets: draft.targets, key },
      {
        onSuccess: (made) => {
          void message.success(t('cmdb.map.added', { count: made.items.length }));
          onClose();
        },
        onError: reportError,
      },
    );
  };

  return (
    <Modal
      open
      title={t('cmdb.map.add_relationship')}
      onCancel={onClose}
      okText={t('cmdb.map.add')}
      okButtonProps={{ loading: add.isPending, 'data-testid': 'ci-relationship-save' }}
      cancelText={t('actions.cancel')}
      onOk={() => {
        form.submit();
      }}
      destroyOnHidden
    >
      <Form<Draft>
        form={form}
        layout="vertical"
        initialValues={{ direction: 'forward', targets: [] }}
        onFinish={submit}
      >
        <Form.Item
          name="type_id"
          label={t('cmdb.field.relationship')}
          rules={[{ required: true, message: t('errors.field.required') }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            loading={types.isPending}
            options={(types.data?.items ?? []).map((x) => ({
              value: x.id,
              label: x.suggested
                ? t('cmdb.map.suggested', { name: relationshipTypeName(t, locale, x) })
                : relationshipTypeName(t, locale, x),
            }))}
            data-testid="ci-relationship-type"
          />
        </Form.Item>
        <Form.Item name="direction" label={t('cmdb.map.direction')}>
          <Radio.Group
            options={(['forward', 'inverse'] as const).map((direction) => ({
              value: direction,
              label: t(`cmdb.map.direction_reads.${direction}`, {
                name: ci.name,
                relationship: relationshipName(t, locale, chosen, direction),
              }),
            }))}
            data-testid="ci-relationship-direction"
          />
        </Form.Item>
        <Form.Item
          name="targets"
          label={t('cmdb.map.targets')}
          extra={t('cmdb.map.targets_max', { count: TARGETS_MAX })}
          rules={[
            { required: true, message: t('errors.field.required') },
            {
              validator: (_, value: string[] | undefined) =>
                (value?.length ?? 0) > TARGETS_MAX
                  ? Promise.reject(new Error(t('cmdb.map.targets_max', { count: TARGETS_MAX })))
                  : Promise.resolve(),
            },
          ]}
        >
          <Select
            mode="multiple"
            showSearch
            filterOption={false}
            onSearch={setSearch}
            loading={picker.isFetching}
            maxCount={TARGETS_MAX}
            options={(picker.data?.items ?? [])
              .filter((x) => x.id !== ci.id)
              .map((x) => ({ value: x.id, label: `${x.display_id} · ${x.name}` }))}
            data-testid="ci-relationship-targets"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
