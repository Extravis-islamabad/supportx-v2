import { useQuery } from '@tanstack/react-query';
import Constants from 'expo-constants';
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useLabels } from '@supportx/labels';

import { Button } from '../components/Button';
import { InfoRow } from '../components/InfoRow';
import { LanguagePicker } from '../components/LanguagePicker';
import { Screen } from '../components/Screen';
import { checkServer } from '../serverAddress';
import { appSide, useMe, useSignOut, useSwitchTenant } from '../session';
import { AvailabilitySwitch } from '../tech/parts';
import { useSettings } from '../settings';
import { SPACE, usePalette } from '../theme';

/** How often the server's status is asked again while this screen is open. */
const HEALTH_INTERVAL_MS = 30_000;

/** The person, their organisation (and the others they can switch to), language, sign-out. */
export function MeScreen({
  onSignedOut,
  onChangeServer,
}: {
  onSignedOut: () => void;
  onChangeServer: () => void;
}) {
  // Technicians also get the Available / Away switch (the prototype's Me tab).
  const t = useLabels();
  const palette = usePalette();
  const server = useSettings((state) => state.server);
  const me = useMe();
  const signOut = useSignOut();
  const switchTenant = useSwitchTenant();
  const [switching, setSwitching] = useState<string | null>(null);
  const [problem, setProblem] = useState(false);
  const health = useQuery({
    queryKey: ['mobile', 'server-health', server],
    queryFn: () => checkServer(server ?? ''),
    enabled: server !== null,
    refetchInterval: HEALTH_INTERVAL_MS,
  });
  const status = health.data === undefined ? 'checking' : health.data.ok ? 'online' : 'offline';

  async function changeTenant(id: string) {
    setSwitching(id);
    setProblem(false);
    try {
      await switchTenant(id);
    } catch {
      setProblem(true);
    }
    setSwitching(null);
  }

  const others = (me.data?.tenants ?? []).filter((tenant) => tenant.id !== me.data?.tenant.id);

  return (
    <Screen title={t('mobile.me.title')}>
      {me.data !== undefined ? (
        <View style={styles.section}>
          <InfoRow testID="me-name" label={t('mobile.me.name')} value={me.data.user.display_name} />
          <InfoRow label={t('mobile.me.email')} value={me.data.user.email} />
          <InfoRow
            testID="me-tenant"
            label={t('mobile.me.organisation')}
            value={me.data.tenant.name}
          />
        </View>
      ) : null}
      {others.length > 0 ? (
        <View style={styles.section}>
          <Text style={[styles.heading, { color: palette.textSecondary }]}>
            {t('mobile.me.switch')}
          </Text>
          {others.map((tenant) => (
            <Button
              key={tenant.id}
              testID={`tenant-${tenant.id}`}
              variant="plain"
              title={tenant.name}
              busy={switching === tenant.id}
              onPress={() => void changeTenant(tenant.id)}
            />
          ))}
          {problem ? (
            <Text accessibilityLiveRegion="polite" style={{ color: palette.error }}>
              {t('mobile.me.switch_failed')}
            </Text>
          ) : null}
        </View>
      ) : null}
      {me.data !== undefined && appSide(me.data) === 'technician' ? (
        <View style={styles.section}>
          <Text style={[styles.heading, { color: palette.textSecondary }]}>
            {t('availability.member_label')}
          </Text>
          <AvailabilitySwitch userId={me.data.user.id} wide />
          <Text style={{ color: palette.textSecondary, fontSize: 12 }}>
            {t('mobile.me.availability_help')}
          </Text>
        </View>
      ) : null}
      <LanguagePicker />
      <View style={styles.section}>
        <InfoRow
          label={t('mobile.about.server')}
          value={server === null ? '' : new URL(server).host}
        />
        <InfoRow
          testID="server-status"
          label={t('mobile.about.server_status')}
          value={t(`api_status.${status}`)}
        />
        {health.data?.ok === true ? (
          <InfoRow
            testID="server-version"
            label={t('mobile.about.server_version')}
            value={health.data.version}
          />
        ) : null}
        <InfoRow
          label={t('mobile.about.app_version')}
          value={Constants.expoConfig?.version ?? ''}
        />
      </View>
      <Button
        testID="sign-out"
        title={t('mobile.me.sign_out')}
        onPress={() => {
          void signOut().then(onSignedOut);
        }}
      />
      <Button
        testID="change-server"
        variant="plain"
        title={t('mobile.server.change')}
        onPress={onChangeServer}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  section: { gap: SPACE.xs },
  heading: { fontSize: 15, marginBottom: SPACE.xs },
});
