import { router } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useAvailability, useSetAvailability, type components } from '@supportx/api-client';
import { useLabels } from '@supportx/labels';

import { slaView, useNow } from '../sla';
import { usePalette } from '../theme';
import { priorityTone, statusCategoryTone } from '../tones';
import { Card, Chip, Row, useToast } from '../ui';

type ListItem = components['schemas']['WorkItemListItem'];
type Person = components['schemas']['PersonOut'];

/** Every page's people in one map (pages each carry the people they name). */
export function mergePeople(
  pages: { people?: Record<string, Person> }[] | undefined,
): Record<string, Person> {
  const all: Record<string, Person> = {};
  for (const page of pages ?? []) Object.assign(all, page.people ?? {});
  return all;
}

export function personName(
  people: Record<string, Person> | undefined,
  id: string | null | undefined,
): string | null {
  if (id === null || id === undefined) return null;
  return people?.[id]?.display_name ?? null;
}

/** One incident in a list: ID, priority, status, subject, owner and its SLA. */
export function IncidentRow({
  item,
  people,
  meId,
}: {
  item: ListItem;
  people: Record<string, Person> | undefined;
  meId: string | undefined;
}) {
  const t = useLabels();
  const palette = usePalette();
  const now = useNow();
  const sla = slaView(t, now, item);
  const owner =
    item.technician_id === null
      ? t('work_item_view.unassigned')
      : item.technician_id === meId
        ? t('mobile.you')
        : (personName(people, item.technician_id) ?? '');
  return (
    <Card
      testID={`incident-${item.display_id}`}
      label={`${item.display_id} ${item.subject}`}
      onPress={() => {
        router.push(`/t/incident/${item.id}`);
      }}
    >
      <Row>
        <Text style={[styles.id, { color: palette.textSecondary }]}>{item.display_id}</Text>
        <Chip text={t(`priority.${item.priority}`)} tone={priorityTone(item.priority)} />
        <Chip
          text={t(`work_item_status.${item.status}`)}
          tone={statusCategoryTone(item.status_category)}
        />
      </Row>
      <Text style={[styles.subject, { color: palette.text }]}>{item.subject}</Text>
      <View style={styles.foot}>
        <Text style={[styles.meta, { color: palette.textSecondary }]}>{owner}</Text>
        <Text style={[styles.meta, styles.sla, { color: sla.tone.fg }]}>{sla.text}</Text>
      </View>
    </Card>
  );
}

/**
 * Available / Away (automation's availability, REQ-AUTO): while Away, auto-assignment skips the
 * technician. The same switch as on the web.
 */
export function AvailabilitySwitch({ userId, wide = false }: { userId: string; wide?: boolean }) {
  const t = useLabels();
  const availability = useAvailability([userId]);
  const change = useSetAvailability();
  const show = useToast((state) => state.show);
  const away = availability.data?.[0]?.state === 'away';
  const tone = away
    ? { bg: '#F2F4F7', fg: '#475467', border: '#D0D5DD', dot: '#98A2B3' }
    : { bg: '#ECFDF3', fg: '#067647', border: '#ABEFC6', dot: '#17B26A' };
  return (
    <Pressable
      testID="availability"
      accessibilityRole="switch"
      accessibilityState={{ checked: !away, busy: change.isPending }}
      accessibilityLabel={t('availability.member_label')}
      disabled={change.isPending || availability.data === undefined}
      onPress={() => {
        const state = away ? 'available' : 'away';
        change.mutate(
          { userId, state },
          {
            onSuccess: () => {
              show(t(state === 'away' ? 'mobile.toast.away' : 'mobile.toast.available'));
            },
          },
        );
      }}
      style={[
        styles.pill,
        wide && styles.wide,
        { backgroundColor: tone.bg, borderColor: tone.border },
      ]}
    >
      <View style={[styles.dot, { backgroundColor: tone.dot }]} />
      <Text style={[styles.pillText, { color: tone.fg }]}>
        {t(away ? 'availability.away' : 'availability.available')}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  id: { fontSize: 12, fontWeight: '600' },
  subject: { fontSize: 15, fontWeight: '600' },
  foot: { flexDirection: 'row', justifyContent: 'space-between', gap: 8 },
  meta: { fontSize: 12 },
  sla: { fontWeight: '600' },
  pill: {
    minHeight: 36,
    paddingHorizontal: 12,
    borderRadius: 999,
    borderWidth: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  wide: { minHeight: 44, justifyContent: 'center', borderRadius: 12 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  pillText: { fontSize: 13, fontWeight: '600' },
});
