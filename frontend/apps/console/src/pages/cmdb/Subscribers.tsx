import { EditOutlined } from '@ant-design/icons';
import { App, Flex, Form, List, Modal, Select, Typography } from 'antd';
import { useState } from 'react';

import {
  useSetCiSubscribers,
  useStructure,
  useUnits,
  type Ci,
  type CiSubscribers,
  type SubscriberKind,
} from '@supportx/api-client';
import { ToneTag, WriteButton, reportError, useLabel } from '@supportx/ui';

const KINDS: readonly SubscriberKind[] = ['department', 'site', 'group'];

/**
 * A business service's subscribers (0185, D-172 (3)): the departments, sites and groups it
 * serves, and how many active people they reach, each counted once. A unit removed since reads
 * "Removed"; one the reader may not see reads "Hidden", never its ID.
 */
export function SubscribersSection({ ci, found }: { ci: Ci; found: CiSubscribers }) {
  const t = useLabel();
  const [editing, setEditing] = useState(false);
  return (
    <Flex vertical gap={8} data-testid="ci-subscribers">
      <Typography.Text>{t('cmdb.subscribers.people', { total: found.people })}</Typography.Text>
      {found.items.length === 0 ? (
        <Typography.Text type="secondary">{t('cmdb.subscribers.none')}</Typography.Text>
      ) : (
        <List
          size="small"
          dataSource={found.items}
          renderItem={(item) => (
            <List.Item key={`${item.kind}:${item.ref_id}`} data-testid="ci-subscriber">
              <Flex gap={8} wrap align="center">
                <Typography.Text type="secondary">
                  {t(`audience_kind.${item.kind}`)}
                </Typography.Text>
                <Typography.Text>{item.name.label ?? t('cmdb.subscribers.hidden')}</Typography.Text>
                {item.removed && <ToneTag tone="warning">{t('cmdb.subscribers.removed')}</ToneTag>}
              </Flex>
            </List.Item>
          )}
        />
      )}
      {ci.can_edit && (
        <WriteButton
          icon={<EditOutlined />}
          onClick={() => {
            setEditing(true);
          }}
          data-testid="ci-subscribers-edit"
        >
          {t('cmdb.subscribers.edit')}
        </WriteButton>
      )}
      {editing && (
        <EditSubscribers
          ci={ci}
          found={found}
          onClose={() => {
            setEditing(false);
          }}
        />
      )}
    </Flex>
  );
}

function EditSubscribers({
  ci,
  found,
  onClose,
}: {
  ci: Ci;
  found: CiSubscribers;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const save = useSetCiSubscribers(ci.id);
  const departments = useStructure('departments');
  const sites = useUnits('sites');
  const groups = useUnits('groups');
  const [chosen, setChosen] = useState<Record<SubscriberKind, string[]>>(() => {
    const start: Record<SubscriberKind, string[]> = { department: [], site: [], group: [] };
    for (const item of found.items) start[item.kind].push(item.ref_id);
    return start;
  });
  const options: Record<SubscriberKind, { value: string; label: string }[]> = {
    department: (departments.data ?? [])
      .filter((d) => !d.disabled || chosen.department.includes(d.id))
      .map((d) => ({ value: d.id, label: d.name })),
    site: (sites.data ?? []).map((s) => ({ value: s.id, label: s.name })),
    group: (groups.data ?? []).map((g) => ({ value: g.id, label: g.name })),
  };
  // A ref already chosen but not offered (removed, or hidden from this reader) keeps a label.
  const known = new Map(found.items.map((i) => [i.ref_id, i]));
  const labelled = (kind: SubscriberKind) => {
    const offered = new Set(options[kind].map((o) => o.value));
    const kept = chosen[kind]
      .filter((value) => !offered.has(value))
      .map((value) => {
        const item = known.get(value);
        const name = item?.name.label ?? t('cmdb.subscribers.hidden');
        return {
          value,
          label: item?.removed ? `${name} (${t('cmdb.subscribers.removed')})` : name,
        };
      });
    return [...options[kind], ...kept];
  };
  return (
    <Modal
      open
      title={t('cmdb.subscribers.edit_title')}
      onCancel={onClose}
      okText={t('actions.save')}
      cancelText={t('actions.cancel')}
      confirmLoading={save.isPending}
      onOk={() => {
        save.mutate(
          {
            version: ci.version,
            subscribers: KINDS.flatMap((kind) => chosen[kind].map((ref_id) => ({ kind, ref_id }))),
          },
          {
            onSuccess: () => {
              void message.success(t('cmdb.subscribers.saved'));
              onClose();
            },
            onError: reportError,
          },
        );
      }}
      data-testid="ci-subscribers-dialog"
    >
      <Form layout="vertical">
        {KINDS.map((kind) => (
          <Form.Item key={kind} label={t(`audience_kind.${kind}`)} htmlFor={`subscribers-${kind}`}>
            <Select
              id={`subscribers-${kind}`}
              mode="multiple"
              showSearch
              optionFilterProp="label"
              value={chosen[kind]}
              options={labelled(kind)}
              onChange={(next: string[]) => {
                setChosen((current) => ({ ...current, [kind]: next }));
              }}
              data-testid={`ci-subscribers-${kind}`}
            />
          </Form.Item>
        ))}
      </Form>
    </Modal>
  );
}
