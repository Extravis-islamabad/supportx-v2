import { AppearanceProvider } from '@supportx/ui';

import { HomePage } from './HomePage';

export function App() {
  return (
    <AppearanceProvider>
      <HomePage />
    </AppearanceProvider>
  );
}
