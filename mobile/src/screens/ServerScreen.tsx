import { useState } from 'react';
import { StyleSheet, Text, TextInput } from 'react-native';

import { useLabels } from '@supportx/labels';

import { Button } from '../components/Button';
import { LanguagePicker } from '../components/LanguagePicker';
import { Screen } from '../components/Screen';
import { checkServer, parseServerAddress } from '../serverAddress';
import { useSettings } from '../settings';
import { SPACE, usePalette } from '../theme';

type Problem = 'invalid' | 'https_required' | 'unreachable' | 'not_supportx';

/**
 * First run (and "Change server"): which SupportX server this phone talks to, the SaaS address
 * or an on-prem one (docs/architecture/mobile.md). Saved only once the server answers as SupportX.
 */
export function ServerScreen({
  onConnected,
  allowHttp = __DEV__,
}: {
  onConnected: () => void;
  allowHttp?: boolean;
}) {
  const t = useLabels();
  const palette = usePalette();
  const saved = useSettings((state) => state.server);
  const setServer = useSettings((state) => state.setServer);
  const [address, setAddress] = useState(saved ?? '');
  const [problem, setProblem] = useState<Problem | null>(null);
  const [busy, setBusy] = useState(false);

  async function connect() {
    const parsed = parseServerAddress(address, allowHttp);
    if (!parsed.ok) {
      setProblem(parsed.problem);
      return;
    }
    setBusy(true);
    setProblem(null);
    const result = await checkServer(parsed.origin);
    if (!result.ok) {
      setBusy(false);
      setProblem(result.problem);
      return;
    }
    try {
      await setServer(parsed.origin);
    } catch (error) {
      // Saving on the device failed (SecureStore): say so instead of spinning for ever.
      if (__DEV__) console.warn('[server check] saving the address failed', error);
      setBusy(false);
      setProblem('unreachable');
      return;
    }
    setBusy(false);
    onConnected();
  }

  return (
    <Screen title={t('mobile.server.title')}>
      <Text style={[styles.intro, { color: palette.textSecondary }]}>
        {t('mobile.server.intro')}
      </Text>
      <Text style={{ color: palette.text }}>{t('mobile.server.address')}</Text>
      <TextInput
        testID="server-address"
        value={address}
        onChangeText={setAddress}
        onSubmitEditing={() => void connect()}
        accessibilityLabel={t('mobile.server.address')}
        placeholder={t('mobile.server.placeholder')}
        placeholderTextColor={palette.placeholder}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        textContentType="URL"
        returnKeyType="go"
        style={[
          styles.input,
          {
            color: palette.text,
            backgroundColor: palette.background,
            borderColor: problem === null ? palette.border : palette.error,
            borderRadius: palette.radius,
          },
        ]}
      />
      {problem !== null ? (
        <Text
          testID="server-problem"
          accessibilityLiveRegion="polite"
          style={{ color: palette.error }}
        >
          {t(`mobile.server.${problem}`)}
        </Text>
      ) : null}
      {busy ? (
        <Text accessibilityLiveRegion="polite" style={{ color: palette.textSecondary }}>
          {t('mobile.server.checking')}
        </Text>
      ) : null}
      <Button
        testID="server-connect"
        title={t('mobile.server.connect')}
        busy={busy}
        onPress={() => void connect()}
      />
      <LanguagePicker />
    </Screen>
  );
}

const styles = StyleSheet.create({
  intro: { fontSize: 15 },
  // Addresses are Latin and read left to right in every language.
  input: {
    borderWidth: 1,
    minHeight: 48,
    paddingHorizontal: SPACE.md,
    fontSize: 16,
    writingDirection: 'ltr',
  },
});
