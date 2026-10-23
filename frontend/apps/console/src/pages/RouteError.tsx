import { useState } from 'react';
import { useRouteError } from 'react-router';

import { CrashPage } from '@supportx/ui';

/**
 * A route failed to render or its chunk failed to load: the friendly crash page, never a trace.
 * The reference printed with the error in the console is the one the user can copy.
 */
export function RouteError() {
  const error = useRouteError();
  const [reference] = useState(() => {
    const id = crypto.randomUUID();
    console.error('[console] route error', id, error);
    return id;
  });
  return <CrashPage reference={reference} />;
}
