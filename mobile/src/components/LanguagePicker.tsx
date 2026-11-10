import { Pressable, StyleSheet, Text, View } from 'react-native';

import { LOCALES, useLabels } from '@supportx/labels';

import { useSettings } from '../settings';
import { SPACE, usePalette } from '../theme';

/** Each language is named in itself (locale.ar is "العربية" in every UI language). */
export function LanguagePicker() {
  const t = useLabels();
  const palette = usePalette();
  const locale = useSettings((state) => state.locale);
  const setLocale = useSettings((state) => state.setLocale);
  return (
    <View accessibilityRole="radiogroup" accessibilityLabel={t('appearance.language')}>
      <Text style={[styles.heading, { color: palette.textSecondary }]}>
        {t('appearance.language')}
      </Text>
      <View style={styles.options}>
        {LOCALES.map((option) => {
          const selected = option === locale;
          return (
            <Pressable
              key={option}
              testID={`language-${option}`}
              accessibilityRole="radio"
              accessibilityState={{ selected }}
              onPress={() => void setLocale(option)}
              style={[
                styles.option,
                { borderColor: palette.primary, borderRadius: palette.radius },
                selected && { backgroundColor: palette.primary },
              ]}
            >
              <Text style={{ color: selected ? palette.onPrimary : palette.text }}>
                {t(`locale.${option}`)}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  heading: { fontSize: 15, marginBottom: SPACE.sm },
  options: { flexDirection: 'row', gap: SPACE.sm, flexWrap: 'wrap' },
  option: { borderWidth: 1, minHeight: 44, paddingHorizontal: SPACE.md, justifyContent: 'center' },
});
