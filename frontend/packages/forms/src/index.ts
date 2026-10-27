// @supportx/forms: React Hook Form + Zod helpers (WP-010). Server field errors (RFC 9457
// `errors[]`) land under the matching field; every message is a translated label.
// The metadata-driven form renderer (architecture.md §6.6) is added in Stage 1.
export { FormField, type FormFieldProps } from './FormField';
export {
  applyServerErrors,
  formFieldOf,
  parseFieldMessage,
  type FieldMessage,
} from './serverErrors';
export { zodResolver } from '@hookform/resolvers/zod';
export {
  Controller,
  useForm,
  type Control,
  type FieldValues,
  type Path,
  type SubmitHandler,
  type UseFormReturn,
} from 'react-hook-form';
export { z } from 'zod';
export { FilterBuilder, type FilterBuilderProps } from './filter/FilterBuilder';
export {
  fromDsl,
  needsValue,
  OPERATORS,
  rowProblems,
  toDsl,
  type FilterChoice,
  type FilterFieldOption,
  type FilterModel,
  type FilterOp,
  type FilterRow,
  type FilterValue,
  type FilterValueType,
} from './filter/model';
