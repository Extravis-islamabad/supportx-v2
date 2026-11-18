import { useAccess } from '@supportx/ui';

/** Whether the person may write CIs this way (`cmdb.manage` covers add, edit and delete). */
export function useCmdbRight() {
  const { can } = useAccess();
  return (right: 'add' | 'edit' | 'delete' | 'configure') =>
    can(`cmdb.${right}`) || (right !== 'configure' && can('cmdb.manage'));
}
