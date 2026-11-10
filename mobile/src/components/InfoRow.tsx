import { StyleSheet, Text, View } from 'react-native';

import { FSI, PDI } from '@supportx/labels';

import { SPACE, usePalette } from '../theme';

/** A label and its value side by side. Values are isolated so a Latin address keeps its order in Arabic. */
export function InfoRow({
  label,
  value,
  testID,
}: {
  label: string;
  value: string;
  testID?: string;
}) {
  const palette = usePalette();
  return (
    <View style={[styles.row, { borderColor: palette.border }]}>
      <Text style={[styles.label, { color: palette.textSecondary }]}>{label}</Text>
      <Text testID={testID} style={[styles.value, { color: palette.text }]}>
        {`${FSI}${value}${PDI}`}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: SPACE.md,
    paddingVertical: SPACE.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  label: { fontSize: 15 },
  value: { fontSize: 15, flexShrink: 1 },
});
