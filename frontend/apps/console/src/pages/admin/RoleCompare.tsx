import { Checkbox, Empty, Flex, Select, Table, Typography } from 'antd';
import { useState } from 'react';

import {
  usePermissionCatalogue,
  useRole,
  type PermissionInfo,
  type RoleDetail,
  type RoleSummary,
} from '@supportx/api-client';
import { Drawer, ToneTag, useLabel } from '@supportx/ui';

import { groupByModule, roleName } from './roleName';

// WP-042 (REQ-ADM-017): two roles side by side, by module, the differences marked.

interface Row {
  key: string;
  module: string;
  permission: PermissionInfo | null;
  first: string | null;
  second: string | null;
}

function scopeOf(role: RoleDetail | undefined, permission: string): string | null {
  return role?.permissions.find((grant) => grant.permission === permission)?.scope ?? null;
}

export function RoleCompare({
  open,
  roles,
  onClose,
}: {
  open: boolean;
  roles: RoleSummary[];
  onClose: () => void;
}) {
  const t = useLabel();
  const [firstId, setFirstId] = useState<string>();
  const [secondId, setSecondId] = useState<string>();
  const [onlyDifferences, setOnlyDifferences] = useState(true);
  const catalogue = usePermissionCatalogue(open);
  const first = useRole(firstId);
  const second = useRole(secondId);
  const ready =
    first.data !== undefined && second.data !== undefined && catalogue.data !== undefined;

  const rows: Row[] = [];
  if (ready) {
    for (const [module, permissions] of groupByModule(catalogue.data)) {
      const inModule = permissions
        .map((permission) => ({
          key: permission.key,
          module,
          permission,
          first: scopeOf(first.data, permission.key),
          second: scopeOf(second.data, permission.key),
        }))
        .filter((row) => !onlyDifferences || row.first !== row.second)
        .filter((row) => row.first !== null || row.second !== null);
      if (inModule.length > 0) {
        rows.push({ key: `module-${module}`, module, permission: null, first: null, second: null });
        rows.push(...inModule);
      }
    }
  }
  const scope = (value: string | null) =>
    value === null ? (
      <Typography.Text type="secondary">{t('roles.compare_not_granted')}</Typography.Text>
    ) : (
      t(`scope.${value}`)
    );
  const options = roles.map((role) => ({ value: role.id, label: roleName(role, t) }));

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={760}
      title={t('roles.compare')}
      destroyOnHidden
      data-testid="role-compare"
    >
      <Flex gap={12} wrap style={{ marginBottom: 16 }}>
        <Select
          style={{ flex: '1 1 240px' }}
          placeholder={t('roles.compare_first')}
          aria-label={t('roles.compare_first')}
          options={options}
          value={firstId}
          onChange={setFirstId}
          data-testid="role-compare-first"
        />
        <Select
          style={{ flex: '1 1 240px' }}
          placeholder={t('roles.compare_second')}
          aria-label={t('roles.compare_second')}
          options={options}
          value={secondId}
          onChange={setSecondId}
          data-testid="role-compare-second"
        />
        <Checkbox
          checked={onlyDifferences}
          onChange={(event) => {
            setOnlyDifferences(event.target.checked);
          }}
          data-testid="role-compare-differences"
        >
          {t('roles.compare_differences')}
        </Checkbox>
      </Flex>
      {!ready ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('roles.compare_pick')} />
      ) : rows.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t('roles.compare_same')}
          data-testid="role-compare-same"
        />
      ) : (
        <Table<Row>
          rowKey="key"
          size="small"
          pagination={false}
          dataSource={rows}
          data-testid="role-compare-table"
          columns={[
            {
              key: 'permission',
              title: t('roles.permissions'),
              render: (_, row) =>
                row.permission === null ? (
                  <Typography.Text strong>{t(`permission_module.${row.module}`)}</Typography.Text>
                ) : (
                  t(`permission.${row.permission.key}`)
                ),
            },
            {
              key: 'first',
              title: roleName(first.data, t),
              render: (_, row) => (row.permission === null ? null : scope(row.first)),
            },
            {
              key: 'second',
              title: roleName(second.data, t),
              render: (_, row) =>
                row.permission === null ? null : (
                  <Flex gap={6} align="center">
                    {scope(row.second)}
                    {row.first !== row.second && (
                      <span data-testid={`role-compare-diff-${row.key}`}>
                        <ToneTag tone="warning">{t('roles.compare_differs')}</ToneTag>
                      </span>
                    )}
                  </Flex>
                ),
            },
          ]}
        />
      )}
    </Drawer>
  );
}
