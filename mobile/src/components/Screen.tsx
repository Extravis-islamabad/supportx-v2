import type { ReactNode } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { SPACE, usePalette } from '../theme';

/**
 * A screen: title (with optional actions beside it), scrolling content, pull to refresh. The
 * bottom edge belongs to the tab bar, so only the top is kept clear of the status bar.
 */
export function Screen({
  title,
  subtitle,
  aside,
  children,
  onRefresh,
  refreshing = false,
}: {
  title: string;
  subtitle?: string;
  aside?: ReactNode;
  children: ReactNode;
  onRefresh?: () => void;
  refreshing?: boolean;
}) {
  const palette = usePalette();
  return (
    <SafeAreaView edges={['top']} style={[styles.safe, { backgroundColor: palette.layout }]}>
      <View style={[styles.accent]} />
      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          onRefresh === undefined ? undefined : (
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          )
        }
      >
        <View style={styles.header}>
          <View style={styles.titles}>
            <Text accessibilityRole="header" style={[styles.title, { color: palette.text }]}>
              {title}
            </Text>
            {subtitle !== undefined ? (
              <Text style={[styles.subtitle, { color: palette.textSecondary }]}>{subtitle}</Text>
            ) : null}
          </View>
          {aside}
        </View>
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  // The brand gradient's ends as a thin line (the prototype's top accent), in one colour here.
  accent: { height: 4, backgroundColor: '#7E40D1' },
  content: { padding: SPACE.md, gap: SPACE.md, paddingBottom: SPACE.lg },
  header: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm },
  titles: { flex: 1, gap: 2 },
  title: { fontSize: 22, fontWeight: '700' },
  subtitle: { fontSize: 14 },
});
