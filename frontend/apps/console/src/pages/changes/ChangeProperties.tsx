import { useChangeDetails, useStagedSettings, type Change } from '@supportx/api-client';
import {
  PropertiesPanel,
  PropertyList,
  useAppearance,
  useLabel,
  type PropertyItem,
} from '@supportx/ui';

import { personName } from '../incidents/labels';
import { listValueName, statusName } from '../staged/labels';

/**
 * The change's properties on the end side (template A): where it is, what kind it is, its risk
 * and its people. Only the fields that hold a value (D-155); editing stays in the tabs.
 */
export function ChangeProperties({ change }: { change: Change }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const details = useChangeDetails(change.id).data;
  const settings = useStagedSettings('changes');
  const own = (list: string, code: string | null | undefined) =>
    code
      ? listValueName(
          t,
          locale,
          list,
          settings.data?.own_lists?.[list]?.find((v) => v.code === code),
          code,
        )
      : null;
  const items: PropertyItem[] = [
    {
      key: 'status',
      label: t('work_item.field.status'),
      content: statusName(t, change.status),
      filled: true,
    },
    {
      key: 'path',
      label: t('changes.col.path'),
      content: change.stage_path ? t(`stage_path.${change.stage_path}`) : null,
      filled: Boolean(change.stage_path),
    },
    {
      key: 'type',
      label: t('work_item.field.change_type'),
      content: own('change_type', details?.change_type),
      filled: Boolean(details?.change_type),
    },
    {
      key: 'reason',
      label: t('work_item.field.change_reason'),
      content: own('change_reason', details?.change_reason),
      filled: Boolean(details?.change_reason),
    },
    {
      key: 'risk',
      label: t('work_item.field.risk'),
      content: details?.risk ? t(`risk_level.${details.risk}`) : null,
      filled: Boolean(details?.risk),
    },
    {
      key: 'owner',
      label: t('work_item_role.change_owner'),
      content: change.technician_id ? personName(change.people, change.technician_id) : null,
      filled: Boolean(change.technician_id),
    },
    {
      key: 'requester',
      label: t('work_item.field.requester_id'),
      content: personName(change.people, change.requester_id),
      filled: true,
    },
  ];
  return (
    <PropertiesPanel
      testId="change-properties"
      sections={[
        {
          key: 'change',
          title: t('changes.properties'),
          children: <PropertyList items={items} testId="change-props" />,
        },
      ]}
    />
  );
}
