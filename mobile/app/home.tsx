import { Redirect } from 'expo-router';
import { ActivityIndicator, View } from 'react-native';

import { appSide, useMe } from '../src/session';
import { useSettings } from '../src/settings';
import { usePalette } from '../src/theme';

/** After sign-in: the technician or the requester side of the one app (D-158). */
export default function HomeRoute() {
  const session = useSettings((state) => state.session);
  const palette = usePalette();
  const me = useMe();
  // Signed out here or elsewhere (a 401 forgets the session): back to the sign-in.
  if (session === null) return <Redirect href="/signin" />;
  if (me.data === undefined) {
    return (
      <View
        style={{
          flex: 1,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: palette.layout,
        }}
      >
        <ActivityIndicator color={palette.primary} />
      </View>
    );
  }
  return <Redirect href={appSide(me.data) === 'technician' ? '/t/home' : '/r/home'} />;
}
