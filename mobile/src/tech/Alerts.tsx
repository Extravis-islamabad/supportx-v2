import { router } from 'expo-router';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { useMarkNotificationsRead, useNotifications } from '@supportx/api-client';
import { useLabels } from '@supportx/labels';
import { usePersonalChannel } from '@supportx/realtime';

import { Button } from '../components/Button';
import { Screen } from '../components/Screen';
import { usePalette } from '../theme';
import { TONES } from '../tones';
import { Card, Muted } from '../ui';

/** In-app notifications (WP-023); tapping one marks it read and opens its record. */
export function Alerts() {
  const t = useLabels();
  const palette = usePalette();
  const notifications = useNotifications();
  const markRead = useMarkNotificationsRead();
  usePersonalChannel(() => {
    void notifications.refetch();
  });
  const items = notifications.data?.pages.flatMap((page) => page.items) ?? [];
  const unread = notifications.data?.pages[0]?.unread ?? 0;

  return (
    <Screen
      title={t('mobile.nav.alerts')}
      refreshing={notifications.isRefetching}
      onRefresh={() => void notifications.refetch()}
      aside={
        unread > 0 ? (
          <Button
            testID="read-all"
            variant="plain"
            title={t('mobile.alerts.read_all')}
            onPress={() => {
              markRead.mutate(undefined);
            }}
          />
        ) : null
      }
    >
      {notifications.isPending ? <ActivityIndicator color={palette.primary} /> : null}
      {!notifications.isPending && items.length === 0 ? (
        <Muted testID="alerts-empty" text={t('mobile.alerts.empty')} />
      ) : null}
      {items.map((item) => (
        <Card
          key={item.id}
          testID={`alert-${item.id}`}
          label={item.title}
          onPress={() => {
            if (!item.read) markRead.mutate([item.id]);
            if (item.record_type === 'incident') router.push(`/t/incident/${item.record_id}`);
            else if (item.record_type === 'service_request') router.replace('/t/approvals');
          }}
        >
          <View style={styles.row}>
            <View
              style={[
                styles.dot,
                {
                  backgroundColor: item.read
                    ? palette.border
                    : item.urgent
                      ? TONES.danger.fg
                      : TONES.info.fg,
                },
              ]}
            />
            <View style={styles.text}>
              <Text
                style={[
                  styles.title,
                  { color: palette.text, fontWeight: item.read ? '400' : '600' },
                ]}
              >
                {item.title}
              </Text>
              <Text style={{ color: palette.textSecondary, fontSize: 12 }}>
                {`${item.display_id} · ${new Date(item.created_at).toLocaleString()}`}
              </Text>
            </View>
          </View>
        </Card>
      ))}
      {notifications.hasNextPage ? (
        <Button
          variant="plain"
          title={t('mobile.queue.more')}
          busy={notifications.isFetchingNextPage}
          onPress={() => void notifications.fetchNextPage()}
        />
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  dot: { width: 8, height: 8, borderRadius: 4, marginTop: 6 },
  text: { flex: 1, gap: 2 },
  title: { fontSize: 14 },
});
