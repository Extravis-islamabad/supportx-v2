import { router } from 'expo-router';

import { MeScreen } from '../../src/screens/MeScreen';

export default function MeRoute() {
  return (
    <MeScreen
      onSignedOut={() => {
        router.replace('/signin');
      }}
      onChangeServer={() => {
        router.push('/server');
      }}
    />
  );
}
