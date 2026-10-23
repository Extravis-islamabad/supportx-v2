// @supportx/api-client: typed access to the SupportX API (architecture.md §9.2).
// Types come from schema.ts, generated from the backend's OpenAPI contract (`make openapi`, D-022);
// calls go through openapi-fetch with the conventions middleware in client.ts (D-026).
export {
  API_BASE,
  api,
  call,
  CSRF_HEADER,
  currentConnectivity,
  etagFor,
  IDEMPOTENCY_HEADER,
  loginUrl,
  onConnectivity,
  rememberEtag,
  reportConnectivity,
  REQUEST_ID_HEADER,
  setCsrfToken,
  type App,
  type Connectivity,
} from './client';
export {
  ApiError,
  asProblem,
  ENTITLEMENT_CODES,
  isApiError,
  type ApiErrorKind,
  type FieldError,
  type ProblemDetail,
} from './errors';
export {
  useEntitlements,
  type EntitlementState,
  type Entitlements,
  type Feature,
} from './entitlements';
export { queryKeys } from './keys';
export type { components, paths } from './schema';
export {
  fetchMe,
  useLogout,
  useSession,
  useSwitchTenant,
  type MeResponse,
  type SessionTenant,
  type SessionUser,
} from './session';
export {
  allOf,
  searchFilter,
  useUpdateUser,
  useUser,
  useUsers,
  type FilterCondition,
  type FilterExpression,
  type UserDetail,
  type UserPage,
  type UserPreferencesPatch,
  type UsersQuery,
} from './users';
