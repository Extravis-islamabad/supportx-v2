import { useQueryClient } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { useIncidents, useIncidentViews } from '@supportx/api-client';
import { useLabels } from '@supportx/labels';
import { useListChannel } from '@supportx/realtime';

import { Button } from '../components/Button';
import { Screen } from '../components/Screen';
import { useMe } from '../session';
import { usePalette } from '../theme';
import { Muted } from '../ui';
import { IncidentRow, mergePeople } from './parts';

/** The queue's filters (the prototype's Mine, My group, Unassigned, Overdue), as server views. */
export const QUEUE_VIEWS = ['my_open', 'my_groups_open', 'unassigned', 'my_overdue'] as const;
type QueueView = (typeof QUEUE_VIEWS)[number] | 'my_due_today';

export function Queue() {
  const t = useLabels();
  const palette = usePalette();
  const queryClient = useQueryClient();
  const me = useMe();
  const params = useLocalSearchParams<{ view?: string }>();
  const view: QueueView =
    params.view === 'my_due_today' || QUEUE_VIEWS.includes(params.view as never)
      ? (params.view as QueueView)
      : 'my_open';
  const views = useIncidentViews();
  const list = useIncidents({ view, limit: 50 });
  useListChannel('incidents', () => {
    void queryClient.invalidateQueries({ queryKey: ['incidents'], refetchType: 'active' });
  });

  const counts = new Map((views.data ?? []).map((v) => [v.view, v.count]));
  const items = list.data?.pages.flatMap((page) => page.items) ?? [];
  const people = mergePeople(list.data?.pages);
  const total = list.data?.pages[0]?.estimated_total ?? items.length;

  return (
    <Screen
      title={t('mobile.nav.queue')}
      refreshing={list.isRefetching}
      onRefresh={() => {
        void queryClient.invalidateQueries({ queryKey: ['incidents'], refetchType: 'active' });
      }}
    >
      <View accessibilityRole="tablist" style={styles.filters}>
        {QUEUE_VIEWS.map((key) => {
          const on = key === view;
          return (
            <Pressable
              key={key}
              testID={`filter-${key}`}
              accessibilityRole="tab"
              accessibilityState={{ selected: on }}
              onPress={() => {
                router.setParams({ view: key });
              }}
              style={[
                styles.filter,
                {
                  backgroundColor: on ? palette.primary : palette.background,
                  borderColor: on ? palette.primary : palette.strongBorder,
                },
              ]}
            >
              <Text style={[styles.filterText, { color: on ? palette.onPrimary : palette.text }]}>
                {`${t(`work_item_view.${key}`)} · ${String(counts.get(key) ?? 0)}`}
              </Text>
            </Pressable>
          );
        })}
      </View>
      <Muted testID="queue-note" text={t('mobile.queue.showing', { shown: items.length, total })} />
      {list.isPending ? <ActivityIndicator color={palette.primary} /> : null}
      {items.map((item) => (
        <IncidentRow key={item.id} item={item} people={people} meId={me.data?.user.id} />
      ))}
      {!list.isPending && items.length === 0 ? (
        <Muted testID="queue-empty" text={t('mobile.queue.empty')} />
      ) : null}
      {list.hasNextPage ? (
        <Button
          variant="plain"
          title={t('mobile.queue.more')}
          busy={list.isFetchingNextPage}
          onPress={() => void list.fetchNextPage()}
        />
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  filters: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  filter: {
    minHeight: 36,
    paddingHorizontal: 14,
    borderRadius: 999,
    borderWidth: 1,
    justifyContent: 'center',
  },
  filterText: { fontSize: 13, fontWeight: '600' },
});
