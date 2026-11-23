import { useQueryClient } from '@tanstack/react-query';
import { Breadcrumb, Flex } from 'antd';
import { Link, useParams } from 'react-router';

import { queryKeys, useCiTypes, type CiType } from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  EmptyText,
  NoAccess,
  SettingsPageHeader,
  useAccess,
  useAppearance,
  useLabel,
} from '@supportx/ui';

import { nameOf } from '../../cmdb/names';
import { CustomFieldsTab } from '../incidents/CustomFieldsTab';
import { ciTypeFieldsHref } from './links';

/**
 * One CI type's custom fields (0175 part 2; template E): its own fields, which CIs of the type and
 * every type below it have, and read-only the fields it inherits from all CI types or from a
 * parent type. Fields are metadata's; changes reach open screens live.
 */
export function CiTypeFieldsPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const { typeId = '' } = useParams();
  const types = useCiTypes();
  const queryClient = useQueryClient();
  useTenantChannel((message) => {
    if (message.type === 'cmdb.config_changed' || message.type === 'refresh') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.all });
    }
  });
  if (!can('cmdb.configure')) return <NoAccess titleKey="nav.admin_cmdb" />;
  const items = types.data?.items ?? [];
  const byId = new Map(items.map((x): [string, CiType] => [x.id, x]));
  const type = byId.get(typeId);
  const name = (x: CiType) => nameOf(t, locale, x, 'cmdb_ci_type');
  if (type === undefined) {
    return types.isPending ? null : (
      <div data-testid="cmdb-type-fields-missing">
        <EmptyText>{t('errors.cmdb_ci_type_not_found')}</EmptyText>
      </div>
    );
  }
  return (
    <Flex vertical gap={16} data-testid="cmdb-type-fields">
      <Breadcrumb
        items={[
          { title: <Link to="/admin/cmdb">{t('nav.admin_cmdb')}</Link> },
          { title: <bdi dir="auto">{name(type)}</bdi> },
        ]}
      />
      <SettingsPageHeader
        title={t('cmdb.fields.title', { type: name(type) })}
        description={t('cmdb.fields.description')}
      />
      <CustomFieldsTab
        key={type.id}
        scope={{
          entity: 'ci',
          typeId: type.id,
          typeName: (id) => {
            const found = byId.get(id);
            return found === undefined ? undefined : name(found);
          },
          typeHref: ciTypeFieldsHref,
        }}
      />
    </Flex>
  );
}
