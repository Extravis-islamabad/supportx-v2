import { useState } from 'react';
import { StyleSheet, Text } from 'react-native';

import { useLabels } from '@supportx/labels';

import { signIn } from '../auth';
import { Button } from '../components/Button';
import { InfoRow } from '../components/InfoRow';
import { LanguagePicker } from '../components/LanguagePicker';
import { Screen } from '../components/Screen';
import { useSettings } from '../settings';
import { usePalette } from '../theme';

type Problem =
  { kind: 'cancelled' } | { kind: 'unreachable' } | { kind: 'error'; code: string | undefined };

/**
 * Sign-in through the organisation's own sign-in page (ADR-039): the system browser opens, and
 * the app gets its session back through a one-time code. No password is typed into the app.
 */
export function SignInScreen({
  onSignedIn,
  onChangeServer,
  start = signIn,
}: {
  onSignedIn: () => void;
  onChangeServer: () => void;
  /** Replaced in tests: the browser step cannot run there. */
  start?: typeof signIn;
}) {
  const t = useLabels();
  const palette = usePalette();
  const server = useSettings((state) => state.server);
  const setSession = useSettings((state) => state.setSession);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);

  async function go() {
    if (server === null) return;
    setBusy(true);
    setProblem(null);
    const result = await start(server);
    if (result.ok) {
      await setSession(result.sessionId);
      setBusy(false);
      onSignedIn();
      return;
    }
    setBusy(false);
    setProblem(
      result.reason === 'error' ? { kind: 'error', code: result.code } : { kind: result.reason },
    );
  }

  const message =
    problem === null
      ? null
      : problem.kind === 'cancelled'
        ? t('mobile.signin.cancelled')
        : problem.kind === 'unreachable'
          ? t('mobile.server.unreachable')
          : t(problem.code === undefined ? 'mobile.signin.failed' : `errors.${problem.code}`);

  return (
    <Screen title={t('mobile.signin.title')}>
      <Text style={[styles.intro, { color: palette.textSecondary }]}>
        {t('mobile.signin.intro')}
      </Text>
      <InfoRow
        label={t('mobile.about.server')}
        value={server === null ? '' : new URL(server).host}
      />
      {message !== null ? (
        <Text
          testID="signin-problem"
          accessibilityLiveRegion="polite"
          style={{ color: palette.error }}
        >
          {message}
        </Text>
      ) : null}
      {busy ? (
        <Text accessibilityLiveRegion="polite" style={{ color: palette.textSecondary }}>
          {t('mobile.signin.waiting')}
        </Text>
      ) : null}
      <Button
        testID="signin"
        title={t('mobile.signin.button')}
        busy={busy}
        onPress={() => void go()}
      />
      <Button
        testID="change-server"
        variant="plain"
        title={t('mobile.server.change')}
        onPress={onChangeServer}
      />
      <LanguagePicker />
    </Screen>
  );
}

const styles = StyleSheet.create({ intro: { fontSize: 15 } });
