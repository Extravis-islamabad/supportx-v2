import { useReleaseDetails, type Release } from '@supportx/api-client';
import { PropertiesPanel, PropertyRow, useAppearance, useDateTime, useLabel } from '@supportx/ui';

import { listValueName, stageName, statusName } from './labels';
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
  const empty = t('releases.not_set');
  const when = (value: string | null | undefined) => (value ? format(value) : empty);
  return (
    <PropertiesPanel
      testId="release-properties"
      sections={[
        {
          key: 'release',
          title: t('releases.properties'),
          children: (
            <>
              <PropertyRow label={t('work_item.field.stage')}>
                {stageName(t, release.stage)}
              </PropertyRow>
              <PropertyRow label={t('work_item.field.status')}>
                {statusName(t, release.status)}
              </PropertyRow>
              <PropertyRow label={t('releases.path')}>
                {release.stage_path ? t(`stage_path.${release.stage_path}`) : empty}
              </PropertyRow>
              <PropertyRow label={t('work_item.field.release_type')}>
                {details?.release_type
                  ? listValueName(t, locale, 'release_type', type, details.release_type)
                  : empty}
              </PropertyRow>
              <PropertyRow label={t('work_item.field.risk')}>
                {details?.risk ? t(`release_risk.${details.risk}`) : empty}
              </PropertyRow>
              <PropertyRow label={t('work_item.field.release_version')}>
                {details?.release_version ? <bdi>{details.release_version}</bdi> : empty}
              </PropertyRow>
            </>
          ),
        },
        {
          key: 'schedule',
          title: t('releases.tab.schedule'),
          children: (
            <>
              <PropertyRow label={t('work_item.field.scheduled_start')}>
                {when(details?.scheduled_start)}
              </PropertyRow>
              <PropertyRow label={t('work_item.field.scheduled_end')}>
                {when(details?.scheduled_end)}
              </PropertyRow>
            </>
          ),
        },
      ]}
    />
  );
}
