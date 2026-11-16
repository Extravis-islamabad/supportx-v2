import { Redirect } from 'expo-router';

import { useSettings } from '../src/settings';

/** First run asks for the server, then the sign-in; after that the app opens on Home. */
export default function Index() {
  const server = useSettings((state) => state.server);
  const session = useSettings((state) => state.session);
  if (server === null) return <Redirect href="/server" />;
  return <Redirect href={session === null ? '/signin' : '/home'} />;
}
