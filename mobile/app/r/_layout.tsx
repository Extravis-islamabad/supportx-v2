import { Redirect, Slot } from 'expo-router';

import { SignedInShell } from '../../src/shell';
import { useSettings } from '../../src/settings';

export default function Layout() {
  const session = useSettings((state) => state.session);
  if (session === null) return <Redirect href="/signin" />;
  return (
    <SignedInShell side="requester">
      <Slot />
    </SignedInShell>
  );
}
