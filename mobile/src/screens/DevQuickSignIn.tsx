import { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useLabels } from '@supportx/labels';

import { Button } from '../components/Button';
import { SPACE, usePalette } from '../theme';

/**
 * Dev-only quick sign-in on the mobile app (D-163): the web's /dev/sign-in (D-151) for the debug
 * build, one button per Showcase Company persona.
 *
 * The real sign-in cannot finish on the local stack: its return link needs a verified https host
 * (ADR-044 item 3). The API answers 404 unless the local dev stack switched quick sign-in on and
 * the call is local (the emulator reaches it through `adb reverse`), so anywhere else this section
 * shows nothing. Release builds never render it (`__DEV__`). Its endpoints are kept out of the
 * OpenAPI document on purpose (not part of the product API), so their shapes are declared here.
 */

interface Persona {
  code: string;
  email: string;
  app: 'console' | 'portal';
  enrolled: boolean;
}

interface Problem {
  message_key?: string;
  params?: Record<string, string | number>;
}

function isPersona(value: unknown): value is Persona {
  if (typeof value !== 'object' || value === null) return false;
  const { code, app } = value as Record<string, unknown>;
  return typeof code === 'string' && (app === 'console' || app === 'portal');
}

const base = (server: string) => `${server.replace(/\/+$/, '')}/api/v1/auth/dev`;

export function DevQuickSignIn({
  server,
  onSession,
}: {
  server: string;
  /** The session the server handed back: kept like the one from the real sign-in. */
  onSession: (sessionId: string) => Promise<void>;
}) {
  const t = useLabels();
  const palette = usePalette();
  const [personas, setPersonas] = useState<Persona[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void fetch(new Request(`${base(server)}/personas`))
      .then(async (answer) => {
        if (answer.ok) return (await answer.json()) as unknown;
        if (__DEV__ && answer.status !== 404) {
          console.warn('[quick sign-in] personas answered', answer.status);
        }
        return null;
      })
      .catch((error: unknown) => {
        if (__DEV__) console.warn('[quick sign-in] personas request failed', server, error);
        return null;
      })
      .then((found) => {
        if (live) setPersonas(Array.isArray(found) ? found.filter(isPersona) : null);
      });
    return () => {
      live = false;
    };
  }, [server]);

  // Switched off, not local, or not a SupportX dev stack: nothing to offer, nothing shown.
  if (personas === null || personas.length === 0) return null;

  async function signIn(persona: Persona) {
    setBusy(persona.code);
    setProblem(null);
    setSentTo(null);
    try {
      const answer = await fetch(
        new Request(`${base(server)}/mobile/sign-in`, {
          method: 'POST',
          // The app's own header: a browser would have to ask first (CORS), so no page can post.
          headers: { 'Content-Type': 'application/json', 'X-SupportX-Client': 'mobile' },
          body: JSON.stringify({ persona: persona.code }),
        }),
      );
      if (answer.ok) {
        const done = (await answer.json()) as {
          session_id: string | null;
          setup_link_sent_to: string | null;
        };
        if (done.session_id) {
          await onSession(done.session_id);
          return;
        }
        // The new starter: Keycloak mailed the two-step set-up link (open it in Mailpit).
        setSentTo(done.setup_link_sent_to);
        return;
      }
      const body = (await answer.json().catch(() => ({}))) as Problem;
      const reason = body.params?.reason;
      // The refusal in words: Keycloak's reason when it gave one (never a raw code).
      setProblem(
        typeof reason === 'string'
          ? t(`dev_sign_in.reason.${reason}`)
          : t(body.message_key ?? 'errors.internal_error', body.params),
      );
    } catch {
      setProblem(t('mobile.server.unreachable'));
    } finally {
      setBusy(null);
    }
  }

  return (
    <View testID="dev-quick-sign-in" style={[styles.box, { borderColor: palette.border }]}>
      <Text accessibilityRole="header" style={[styles.title, { color: palette.text }]}>
        {t('dev_sign_in.title')}
      </Text>
      <Text style={{ color: palette.textSecondary }}>{t('dev_sign_in.warning')}</Text>
      {sentTo !== null ? (
        <Text
          testID="dev-quick-sign-in-sent"
          accessibilityLiveRegion="polite"
          style={{ color: palette.text }}
        >
          {t('dev_sign_in.setup_link_sent', { email: sentTo })}
        </Text>
      ) : null}
      {problem !== null ? (
        <Text
          testID="dev-quick-sign-in-problem"
          accessibilityLiveRegion="polite"
          style={{ color: palette.error }}
        >
          {problem}
        </Text>
      ) : null}
      {personas.map((persona) => (
        <Button
          key={persona.code}
          testID={`dev-quick-sign-in-${persona.code}`}
          variant="plain"
          busy={busy === persona.code}
          title={
            t('dev_sign_in.as', { persona: t(`dev_persona.${persona.code}`) }) +
            (persona.enrolled ? '' : ` — ${t('dev_sign_in.sets_up_mfa')}`)
          }
          onPress={() => {
            if (busy === null) void signIn(persona);
          }}
        />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { borderTopWidth: StyleSheet.hairlineWidth, paddingTop: SPACE.md, gap: SPACE.sm },
  title: { fontSize: 17, fontWeight: '600' },
});
