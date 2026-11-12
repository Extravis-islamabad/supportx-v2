import { Alert, Flex, Select, Tag, Typography } from 'antd';
import type { ReactNode } from 'react';

import type { ServiceRolesOut } from '@supportx/api-client';

import { useLabel } from '../appearance';
import { EmptyText } from '../EmptyText';
import { serviceRoleName } from './serviceRoles';

/**
 * A service identity's roles, for the screen that owns it (a workflow's "Runs as", a
 * connector's settings next; the coordinator, 2026-11-11). It shows the identity, the roles
 * given to it, and a picker of the roles the server says it may hold: nothing beyond that list
 * is ever offered. The owner says what it is for (`help`) and what shows before it exists
 * (`notMade`), and gives and takes roles through its own guarded route.
 */
export function ServiceRolesSection({
  data,
  help,
  notMade,
  readOnly,
  pending,
  onGive,
  onTake,
  testId = 'service-roles',
}: {
  data: ServiceRolesOut;
  help: ReactNode;
  notMade: ReactNode;
  readOnly: boolean;
  pending: boolean;
  onGive: (roleId: string) => void;
  onTake: (roleId: string) => void;
  testId?: string;
}) {
  const t = useLabel();
  const held = new Set(data.roles.map((r) => r.id));
  return (
    <Flex vertical gap={12} data-testid={testId}>
      {help}
      {!data.made ? (
        <EmptyText>{notMade}</EmptyText>
      ) : (
        <>
          <Typography.Text strong data-testid={`${testId}-name`}>
            <bdi dir="auto">{data.name}</bdi>
          </Typography.Text>
          {!data.active && (
            <Typography.Text type="secondary">{t('service_roles.inactive')}</Typography.Text>
          )}
          {data.roles.length === 0 ? (
            <Alert type="warning" showIcon message={t('service_roles.no_roles')} />
          ) : (
            <Flex wrap gap={4} data-testid={`${testId}-held`}>
              {data.roles.map((role) => (
                <Tag
                  key={role.id}
                  closable={!readOnly}
                  onClose={(event) => {
                    event.preventDefault();
                    onTake(role.id);
                  }}
                  closeIcon={
                    <span
                      aria-label={t('service_roles.remove', { name: serviceRoleName(t, role) })}
                    >
                      ×
                    </span>
                  }
                >
                  {serviceRoleName(t, role)}
                </Tag>
              ))}
            </Flex>
          )}
          <Select<string>
            value={null}
            disabled={readOnly || pending}
            placeholder={t('service_roles.add')}
            aria-label={t('service_roles.add')}
            showSearch
            optionFilterProp="label"
            onChange={(roleId) => {
              onGive(roleId);
            }}
            options={data.offered
              .filter((r) => !held.has(r.id))
              .map((r) => ({ value: r.id, label: serviceRoleName(t, r) }))}
            notFoundContent={t('service_roles.none_offered')}
            data-testid={`${testId}-add`}
          />
        </>
      )}
    </Flex>
  );
}
