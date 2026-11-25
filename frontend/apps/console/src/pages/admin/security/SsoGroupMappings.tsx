import { Button, Flex, Input, List, Modal, Radio, Select, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  groupMappingHolders,
  useCreateGroupMapping,
  useGroupMappings,
  useRemoveGroupMapping,
  useRoles,
  useStructure,
  type GroupMapping,
} from '@supportx/api-client';
import {
  FormProblem,
  lengthLimit,
  markHandled,
  reportError,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

import { roleName } from '../roleName';

interface Target {
  kind: 'role' | 'group';
  id: string;
}

/**
 * An SSO set-up's group mappings (WP-057 S5c-1b; REQ-SEC-014): an external group, exactly as
 * the provider sends it, onto one role or one support group. They apply at each sign-in through
 * this provider only (D-188). Removing one that people hold access through asks whether they
 * keep it (made hand-made) or lose it now (the coordinator's Q2).
 */
export function SsoGroupMappings({ providerId }: { providerId: string }) {
  const t = useLabel();
  const mappings = useGroupMappings('sso', providerId);
  const roles = useRoles();
  const groups = useStructure('groups', true, true);
  const create = useCreateGroupMapping();
  const remove = useRemoveGroupMapping();
  const problem = useFormProblem();
  const [external, setExternal] = useState('');
  const [target, setTarget] = useState<Target | null>(null);
  const [removing, setRemoving] = useState<{ mapping: GroupMapping; holders: number } | null>(null);
  const [onHeld, setOnHeld] = useState<'keep' | 'remove'>('keep');

  const roleOptions = (roles.data ?? []).map((r) => ({
    value: `role:${r.id}`,
    label: roleName(r, t),
  }));
  const groupOptions = (groups.data ?? []).map((g) => ({ value: `group:${g.id}`, label: g.name }));
  const targetName = (m: GroupMapping) => {
    if (m.role_id != null) {
      const role = roles.data?.find((r) => r.id === m.role_id);
      return role === undefined ? t('security.groups.unknown_target') : roleName(role, t);
    }
    return (
      groups.data?.find((g) => g.id === m.group_id)?.name ?? t('security.groups.unknown_target')
    );
  };

  const add = () => {
    if (target === null || external.trim() === '') return;
    problem.clear();
    create.mutate(
      {
        source_kind: 'sso',
        source_id: providerId,
        external_group_id: external.trim(),
        ...(target.kind === 'role' ? { role_id: target.id } : { group_id: target.id }),
      },
      {
        onSuccess: () => {
          setExternal('');
          setTarget(null);
        },
        onError: (error) => {
          if (error instanceof ApiError) markHandled(error);
          problem.show(error);
        },
      },
    );
  };

  const startRemove = (mapping: GroupMapping) => {
    groupMappingHolders(mapping.id).then((holders) => {
      if (holders === 0) {
        remove.mutate({ mapping }, { onError: reportError });
        return;
      }
      setOnHeld('keep');
      setRemoving({ mapping, holders });
    }, reportError);
  };

  return (
    <Flex vertical gap={12} data-testid="sso-group-mappings">
      <Typography.Text type="secondary">{t('security.groups.mappings_intro')}</Typography.Text>
      <List
        size="small"
        loading={mappings.isLoading}
        dataSource={mappings.data ?? []}
        locale={{ emptyText: t('security.groups.none') }}
        renderItem={(m) => (
          <List.Item
            key={m.id}
            actions={[
              <Button
                key="remove"
                size="small"
                danger
                onClick={() => {
                  startRemove(m);
                }}
                data-testid={`sso-group-remove-${m.external_group_id}`}
              >
                {t('security.groups.remove')}
              </Button>,
            ]}
          >
            <Typography.Text>
              {t('security.groups.maps_to', { group: m.external_group_id, target: targetName(m) })}
            </Typography.Text>
          </List.Item>
        )}
      />
      <Flex gap={8} wrap align="end">
        <Flex vertical gap={4} style={{ flex: '1 1 200px' }}>
          <label htmlFor="sso-group-external">{t('security.groups.external')}</label>
          <Input
            id="sso-group-external"
            dir="ltr"
            value={external}
            count={lengthLimit(256)}
            onChange={(event) => {
              setExternal(event.target.value);
            }}
            data-testid="sso-group-external"
          />
        </Flex>
        <Flex vertical gap={4} style={{ flex: '1 1 200px' }}>
          <label htmlFor="sso-group-target">{t('security.groups.target')}</label>
          <Select
            id="sso-group-target"
            value={target === null ? undefined : `${target.kind}:${target.id}`}
            onChange={(value: string) => {
              const [kind, id] = value.split(':') as ['role' | 'group', string];
              setTarget({ kind, id });
            }}
            options={[
              { label: t('security.groups.roles'), options: roleOptions },
              { label: t('security.groups.support_groups'), options: groupOptions },
            ]}
            showSearch
            optionFilterProp="label"
            data-testid="sso-group-target"
          />
        </Flex>
        <Button
          onClick={add}
          loading={create.isPending}
          disabled={target === null || external.trim() === ''}
          data-testid="sso-group-add"
        >
          {t('security.groups.add')}
        </Button>
      </Flex>
      <FormProblem problem={problem} />
      <Modal
        open={removing !== null}
        title={t('security.groups.remove_title')}
        okText={t('security.groups.remove')}
        okButtonProps={{ danger: true, loading: remove.isPending }}
        onCancel={() => {
          setRemoving(null);
        }}
        onOk={() => {
          if (removing === null) return;
          remove.mutate(
            { mapping: removing.mapping, onHeld },
            {
              onSuccess: () => {
                setRemoving(null);
              },
              onError: reportError,
            },
          );
        }}
      >
        <Flex vertical gap={8}>
          <Typography.Text>
            {t('security.groups.remove_holders', { count: removing?.holders ?? 0 })}
          </Typography.Text>
          <Radio.Group
            value={onHeld}
            onChange={(event) => {
              setOnHeld(event.target.value as 'keep' | 'remove');
            }}
            data-testid="sso-group-on-held"
          >
            <Flex vertical gap={4}>
              <Radio value="keep">{t('security.groups.keep')}</Radio>
              <Radio value="remove">{t('security.groups.remove_access')}</Radio>
            </Flex>
          </Radio.Group>
        </Flex>
      </Modal>
    </Flex>
  );
}
