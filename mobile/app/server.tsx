import { router } from 'expo-router';

import { ServerScreen } from '../src/screens/ServerScreen';

export default function ServerRoute() {
  // Index decides what comes next: the sign-in for a new server, Home for the same one.
  return (
    <ServerScreen
      onConnected={() => {
        router.replace('/');
      }}
    />
  );
}
