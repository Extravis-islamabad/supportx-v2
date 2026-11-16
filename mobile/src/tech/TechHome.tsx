import { useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { StyleSheet, Text, View } from 'react-native';

import { useIncidents, useIncidentViews } from '@supportx/api-client';
import { useLabels } from '@supportx/labels';
import { useListChannel } from '@supportx/realtime';

import { Screen } from '../components/Screen';
import { useMe } from '../session';
import { useNow } from '../sla';
import { SPACE, usePalette } from '../theme';
import { TONES } from '../tones';
import { Card, Heading, Muted } from '../ui';
import { AvailabilitySwitch, IncidentRow, mergePeople } from './parts';

/** The four numbers on Home, each opening its queue (the prototype's KPIs). */
export const KPI_VIEWS = ['my_open', 'my_overdue', 'my_due_today', 'unassigned'] as const;

/** Technician home: KPIs, a MonetX alert in my groups, and what needs attention now. */
export function TechHome() {
  const t = useLabels();
  const palette = usePalette();
  const queryClient = useQueryClient();
  const me = useMe();
  const views = useIncidentViews();
  const mine = useIncidents({ view: 'my_open', limit: 50 });
  const groups = useIncidents({ view: 'my_groups_open', limit: 50 });
  const now = useNow();
  // Lists, counters and views follow every incident change (rule 5c).
  useListChannel('incidents', () => {
    void queryClient.invalidateQueries({ queryKey: ['incidents'], refetchType: 'active' });
  });

  const counts = new Map((views.data ?? []).map((view) => [view.view, view.count]));
  const items = mine.data?.pages.flatMap((page) => page.items) ?? [];
  const people = mergePeople(mine.data?.pages);
  const groupItems = groups.data?.pages.flatMap((page) => page.items) ?? [];
  const alert = groupItems.find(
    (item) => item.channel === 'monetx' || item.channel === 'alert_webhook',
  );
  const attention = items.filter((item) => {
    if (item.resolution_due_at === null) return false;
    const late =
      Date.parse(item.resolution_due_at) < now || item.resolution_sla_state === 'breached';
    return late || item.resolution_sla_state === 'warning';
  });
  const user = me.data?.user;

  return (
    <Screen
      title={t('mobile.home.greeting', { name: user?.display_name ?? '' })}
      subtitle={me.data?.tenant.name}
      aside={user !== undefined ? <AvailabilitySwitch userId={user.id} /> : null}
      refreshing={views.isRefetching}
      onRefresh={() => {
        void queryClient.invalidateQueries({ queryKey: ['incidents'], refetchType: 'active' });
      }}
    >
      {alert !== undefined ? (
        <Card
          testID="monetx-alert"
          label={alert.subject}
          onPress={() => {
            router.push(`/t/incident/${alert.id}`);
          }}
          style={{ borderColor: '#FECDCA', backgroundColor: '#FFFBFA' }}
        >
          <Text style={[styles.alertKind, { color: TONES.danger.fg }]}>
            {t(`mobile.channel.${alert.channel}`)}
          </Text>
          <Text style={[styles.alertTitle, { color: '#1B1530' }]}>{alert.subject}</Text>
          <Text style={{ color: '#57516B', fontSize: 13 }}>{alert.display_id}</Text>
        </Card>
      ) : null}

      <View style={styles.grid}>
        {KPI_VIEWS.map((view) => (
          <Card
            key={view}
            testID={`kpi-${view}`}
            label={`${t(`work_item_view.${view}`)} ${String(counts.get(view) ?? 0)}`}
            onPress={() => {
              router.replace(`/t/queue?view=${view}`);
            }}
            style={styles.kpi}
          >
            <Text
              style={[
                styles.kpiValue,
                { color: view === 'my_overdue' ? TONES.danger.fg : palette.text },
              ]}
            >
              {counts.has(view) ? String(counts.get(view)) : '–'}
            </Text>
            <Text style={{ color: palette.textSecondary, fontSize: 13 }}>
              {t(`work_item_view.${view}`)}
            </Text>
          </Card>
        ))}
      </View>

      <Heading text={t('mobile.home.attention')} />
      {attention.length === 0 ? (
        <Muted testID="attention-empty" text={t('mobile.home.attention_none')} />
      ) : (
        attention.map((item) => (
          <IncidentRow key={item.id} item={item} people={people} meId={user?.id} />
        ))
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm + 4 },
  kpi: { flexBasis: '47%', flexGrow: 1, minHeight: 88 },
  kpiValue: { fontSize: 28, fontWeight: '700' },
  alertKind: { fontSize: 12, fontWeight: '600' },
  alertTitle: { fontSize: 15, fontWeight: '600' },
});
