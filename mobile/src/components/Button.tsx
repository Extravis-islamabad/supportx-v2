import { ActivityIndicator, Pressable, StyleSheet, Text } from 'react-native';

import { SPACE, usePalette } from '../theme';

export interface ButtonProps {
  title: string;
  onPress: () => void;
  busy?: boolean;
  variant?: 'primary' | 'plain';
  testID?: string;
}

export function Button({ title, onPress, busy = false, variant = 'primary', testID }: ButtonProps) {
  const palette = usePalette();
  const primary = variant === 'primary';
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityState={{ busy, disabled: busy }}
      disabled={busy}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        { borderRadius: palette.radius, borderColor: palette.primary },
        primary && { backgroundColor: pressed ? palette.primaryPressed : palette.primary },
      ]}
    >
      {busy ? <ActivityIndicator color={primary ? palette.onPrimary : palette.primary} /> : null}
      <Text style={[styles.text, { color: primary ? palette.onPrimary : palette.text }]}>
        {title}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    minHeight: 48,
    paddingHorizontal: SPACE.md,
    borderWidth: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: SPACE.sm,
  },
  text: { fontSize: 16, fontWeight: '600' },
});
