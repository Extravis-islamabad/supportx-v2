import type { ReactNode } from 'react';
import {
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { create } from 'zustand';

import { SPACE, usePalette } from './theme';
import type { Tone } from './tones';

/** A small coloured label: priority, status, SLA. The words carry the meaning, not the colour. */
export function Chip({ text, tone, testID }: { text: string; tone: Tone; testID?: string }) {
  return (
    <View style={[styles.chip, { backgroundColor: tone.bg }]}>
      <Text testID={testID} style={[styles.chipText, { color: tone.fg }]}>
        {text}
      </Text>
    </View>
  );
}

/** A white card; pressable when `onPress` is given (a real button for screen readers). */
export function Card({
  children,
  onPress,
  testID,
  label,
  style,
}: {
  children: ReactNode;
  onPress?: () => void;
  testID?: string;
  label?: string;
  style?: StyleProp<ViewStyle>;
}) {
  const palette = usePalette();
  const look = [
    styles.card,
    { backgroundColor: palette.background, borderColor: palette.border },
    style,
  ];
  if (onPress === undefined) {
    return (
      <View testID={testID} style={look}>
        {children}
      </View>
    );
  }
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      style={({ pressed }) => [look, pressed && { opacity: 0.85 }]}
    >
      {children}
    </Pressable>
  );
}

export function Row({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.row, style]}>{children}</View>;
}

/** Section heading inside a screen. */
export function Heading({ text }: { text: string }) {
  const palette = usePalette();
  return (
    <Text accessibilityRole="header" style={[styles.heading, { color: palette.text }]}>
      {text}
    </Text>
  );
}

export function Muted({ text, testID }: { text: string; testID?: string }) {
  const palette = usePalette();
  return (
    <Text testID={testID} style={[styles.muted, { color: palette.textSecondary }]}>
      {text}
    </Text>
  );
}

/** A labelled multi-line field. */
export function Field({
  label,
  value,
  onChange,
  placeholder,
  error,
  testID,
  lines = 3,
  tint,
}: {
  label: string;
  value: string;
  onChange: (text: string) => void;
  placeholder?: string;
  error?: string | null;
  testID?: string;
  lines?: number;
  tint?: { bg: string; border: string };
}) {
  const palette = usePalette();
  return (
    <View style={styles.field}>
      <Text style={[styles.fieldLabel, { color: palette.text }]}>{label}</Text>
      <TextInput
        testID={testID}
        value={value}
        onChangeText={onChange}
        accessibilityLabel={label}
        placeholder={placeholder}
        placeholderTextColor={palette.placeholder}
        multiline={lines > 1}
        numberOfLines={lines}
        style={[
          styles.input,
          {
            minHeight: lines > 1 ? 24 * lines + 20 : 48,
            color: palette.text,
            backgroundColor: tint?.bg ?? palette.background,
            borderColor:
              error !== null && error !== undefined
                ? palette.error
                : (tint?.border ?? palette.strongBorder),
          },
        ]}
      />
      {error !== null && error !== undefined ? (
        <Text accessibilityLiveRegion="polite" style={{ color: palette.error, fontWeight: '600' }}>
          {error}
        </Text>
      ) : null}
    </View>
  );
}

/** A bottom sheet over the screen (resolve, reject): a real modal for screen readers. */
export function Sheet({
  visible,
  title,
  onClose,
  children,
}: {
  visible: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const palette = usePalette();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.scrim}>
        <View
          accessibilityViewIsModal
          style={[styles.sheet, { backgroundColor: palette.background }]}
        >
          <Text accessibilityRole="header" style={[styles.sheetTitle, { color: palette.text }]}>
            {title}
          </Text>
          {children}
        </View>
      </View>
    </Modal>
  );
}

// --- toast ---------------------------------------------------------------------------------------

interface ToastState {
  message: string | null;
  show: (message: string) => void;
}

let toastTimer: ReturnType<typeof setTimeout> | null = null;

export const useToast = create<ToastState>()((set) => ({
  message: null,
  show: (message) => {
    if (toastTimer !== null) clearTimeout(toastTimer);
    set({ message });
    toastTimer = setTimeout(() => {
      set({ message: null });
    }, 2800);
  },
}));

/** The confirmation line after an action ("You took INC-12"), announced politely. */
export function Toast() {
  const message = useToast((state) => state.message);
  if (message === null) return null;
  return (
    <View pointerEvents="none" style={styles.toastWrap}>
      <View style={styles.toast}>
        <Text testID="toast" accessibilityLiveRegion="polite" style={styles.toastText}>
          {message}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  chip: { borderRadius: 999, paddingHorizontal: SPACE.sm, paddingVertical: 2 },
  chipText: { fontSize: 12, fontWeight: '600' },
  card: { borderWidth: 1, borderRadius: 16, padding: 14, gap: 6 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  heading: { fontSize: 17, fontWeight: '700', marginTop: SPACE.xs },
  muted: { fontSize: 13 },
  field: { gap: 6 },
  fieldLabel: { fontSize: 13, fontWeight: '600' },
  input: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 10,
    fontSize: 15,
    textAlignVertical: 'top',
  },
  scrim: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(20, 16, 30, 0.45)' },
  sheet: {
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    padding: SPACE.md,
    paddingBottom: 28,
    gap: 10,
  },
  sheetTitle: { fontSize: 18, fontWeight: '700' },
  toastWrap: { position: 'absolute', left: 16, right: 16, bottom: 88 },
  toast: { backgroundColor: '#1B1530', borderRadius: 12, padding: 12 },
  toastText: { color: '#FFFFFF', fontSize: 14, fontWeight: '500' },
});
