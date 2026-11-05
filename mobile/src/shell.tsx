import Ionicons from '@expo/vector-icons/Ionicons';
import { router, usePathname } from 'expo-router';
import type { ComponentProps, ReactNode } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useMyApprovals, useNotifications } from '@supportx/api-client';
import { useLabels } from '@supportx/labels';
import { RealtimeProvider } from '@supportx/realtime';

import { appSide, useMe, type AppSide } from './session';
import { usePalette } from './theme';
import { Toast } from './ui';

type IconName = ComponentProps<typeof Ionicons>['name'];

interface Tab {
  key: string;
  href: string;
  icon: IconName;
  badge?: number;
}

/** The technician's badge counts: approvals waiting and unread alerts (they update live). */
function useTechBadges(enabled: boolean): { approvals: number; alerts: number } {
  const approvals = useMyApprovals();
  const alerts = useNotifications(enabled);
  return {
    approvals: enabled ? (approvals.data?.items.length ?? 0) : 0,
    alerts: enabled ? (alerts.data?.pages[0]?.unread ?? 0) : 0,
  };
}

function tabsFor(side: AppSide, badges: { approvals: number; alerts: number }): Tab[] {
  if (side === 'requester') {
    return [
      { key: 'home', href: '/r/home', icon: 'home-outline' },
      { key: 'report', href: '/r/report', icon: 'add-circle-outline' },
      { key: 'requests', href: '/r/requests', icon: 'list-outline' },
      { key: 'me', href: '/r/me', icon: 'person-outline' },
    ];
  }
  return [
    { key: 'home', href: '/t/home', icon: 'home-outline' },
    { key: 'queue', href: '/t/queue', icon: 'list-outline' },
    {
      key: 'approvals',
      href: '/t/approvals',
      icon: 'checkmark-circle-outline',
      badge: badges.approvals,
    },
    { key: 'alerts', href: '/t/alerts', icon: 'notifications-outline', badge: badges.alerts },
    { key: 'me', href: '/t/me', icon: 'person-outline' },
  ];
}

function BottomNav({ side }: { side: AppSide }) {
  const t = useLabels();
  const palette = usePalette();
  const insets = useSafeAreaInsets();
  const path = usePathname();
  const badges = useTechBadges(side === 'technician');
  const tabs = tabsFor(side, badges);
  return (
    <View
      accessibilityRole="tablist"
      style={[
        styles.nav,
        {
          backgroundColor: palette.background,
          borderColor: palette.border,
          paddingBottom: Math.max(insets.bottom, 8),
        },
      ]}
    >
      {tabs.map((tab) => {
        const active = path === tab.href || path.startsWith(`${tab.href}/`);
        const color = active ? palette.link : palette.textSecondary;
        return (
          <Pressable
            key={tab.key}
            testID={`tab-${tab.key}`}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            accessibilityLabel={t(`mobile.nav.${tab.key}`)}
            onPress={() => {
              router.replace(tab.href);
            }}
            style={styles.tab}
          >
            <Ionicons name={tab.icon} size={22} color={color} />
            <Text style={[styles.tabLabel, { color }]}>{t(`mobile.nav.${tab.key}`)}</Text>
            {tab.badge !== undefined && tab.badge > 0 ? (
              <View style={styles.badge}>
                <Text style={styles.badgeText}>{tab.badge > 99 ? '99+' : String(tab.badge)}</Text>
              </View>
            ) : null}
          </Pressable>
        );
      })}
    </View>
  );
}

/**
 * The signed-in frame for one side of the app (D-139): one live connection for the session
 * (architecture.md §8; it follows a tenant switch), the screen, the bottom bar and the toast.
 */
export function SignedInShell({ side, children }: { side: AppSide; children: ReactNode }) {
  const palette = usePalette();
  const me = useMe();
  if (me.data === undefined) {
    return (
      <View style={[styles.loading, { backgroundColor: palette.layout }]}>
        <ActivityIndicator color={palette.primary} />
      </View>
    );
  }
  if (appSide(me.data) !== side) {
    // A tenant switch can change the side: go where this person belongs.
    router.replace(appSide(me.data) === 'technician' ? '/t/home' : '/r/home');
  }
  return (
    <RealtimeProvider tenantId={me.data.tenant.id} userId={me.data.user.id}>
      <View style={[styles.frame, { backgroundColor: palette.layout }]}>
        <View style={styles.body}>{children}</View>
        <BottomNav side={side} />
        <Toast />
      </View>
    </RealtimeProvider>
  );
}

const styles = StyleSheet.create({
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  frame: { flex: 1 },
  body: { flex: 1 },
  nav: { flexDirection: 'row', borderTopWidth: 1, paddingTop: 6 },
  tab: { flex: 1, alignItems: 'center', justifyContent: 'center', minHeight: 48, gap: 2 },
  tabLabel: { fontSize: 11, fontWeight: '600' },
  badge: {
    position: 'absolute',
    top: 0,
    end: '22%',
    minWidth: 18,
    height: 18,
    paddingHorizontal: 5,
    borderRadius: 999,
    backgroundColor: '#B42318',
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeText: { color: '#FFFFFF', fontSize: 11, fontWeight: '700' },
});
