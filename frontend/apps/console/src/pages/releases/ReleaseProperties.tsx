import { useReleaseDetails, type Release } from '@supportx/api-client';
import {
  PropertiesPanel,
  PropertyList,
  useAppearance,
  useDateTime,
  useLabel,
  type PropertyItem,
} from '@supportx/ui';

import { listValueName, statusName } from './labels';
import { useOwnList } from './lists';

/**
 * The release's properties on the end side (UI pass 2's record layout; QA6-REL-01): where it is,
 * what kind it is and when it is planned. Editing stays in the Details tab; this panel reads.
 */
export function ReleaseProperties({ id, release }: { id: string; release: Release }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { format } = useDateTime();
  const details = useReleaseDetails(id).data;
  const types = useOwnList('release_type');
  const type = types.find((v) => v.code === details?.release_type);
  // D-155: only the fields that hold a value, then "Add details (n)"; never rows of "Not set".
  // The stage is the stage bar's, so it is not repeated here.
  const items: PropertyItem[] = [
    {
      key: 'status',
      label: t('work_item.field.status'),
      content: statusName(t, release.status),
      filled: true,
    },
    {
      key: 'path',
      label: t('releases.path'),
      content: release.stage_path ? t(`stage_path.${release.stage_path}`) : null,
      filled: Boolean(release.stage_path),
    },
    {
      key: 'type',
      label: t('work_item.field.release_type'),
      content: details?.release_type
        ? listValueName(t, locale, 'release_type', type, details.release_type)
        : null,
      filled: Boolean(details?.release_type),
    },
    {
      key: 'risk',
      label: t('work_item.field.risk'),
      content: details?.risk ? t(`release_risk.${details.risk}`) : null,
      filled: Boolean(details?.risk),
    },
    {
      key: 'version',
      label: t('work_item.field.release_version'),
      content: details?.release_version ? <bdi>{details.release_version}</bdi> : null,
      filled: Boolean(details?.release_version),
    },
  ];
  const scheduled = Boolean(details?.scheduled_start) || Boolean(details?.scheduled_end);
  const schedule: PropertyItem[] = [
    {
      key: 'start',
      label: t('work_item.field.scheduled_start'),
      content: details?.scheduled_start ? format(details.scheduled_start) : null,
      filled: Boolean(details?.scheduled_start),
    },
    {
      key: 'end',
      label: t('work_item.field.scheduled_end'),
      content: details?.scheduled_end ? format(details.scheduled_end) : null,
      filled: Boolean(details?.scheduled_end),
    },
  ];
  return (
    <PropertiesPanel
      testId="release-properties"
      sections={[
        {
          key: 'release',
          title: t('releases.properties'),
          children: <PropertyList items={items} testId="release-props" />,
        },
        // Nothing scheduled yet: no empty Schedule card (D-155); the Schedule tab plans it.
        ...(scheduled
          ? [
              {
                key: 'schedule',
                title: t('releases.tab.schedule'),
                children: <PropertyList items={schedule} testId="release-schedule" />,
              },
            ]
          : []),
      ]}
    />
  );
}
