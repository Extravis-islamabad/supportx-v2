import { router } from 'expo-router';

import { SignInScreen } from '../src/screens/SignInScreen';

export default function SignInRoute() {
  return (
    <SignInScreen
      onSignedIn={() => {
        router.replace('/home');
      }}
      onChangeServer={() => {
        router.push('/server');
      }}
    />
  );
}
