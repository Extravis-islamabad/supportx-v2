import { Form } from 'antd';
import type { ReactElement } from 'react';
import {
  Controller,
  type Control,
  type ControllerRenderProps,
  type FieldValues,
  type Path,
} from 'react-hook-form';

import { useLabels, type LabelKey, type LabelParams } from '@supportx/labels';

import { parseFieldMessage } from './serverErrors';

export interface FormFieldProps<T extends FieldValues, N extends Path<T> = Path<T>> {
  control: Control<T>;
  name: N;
  labelKey: LabelKey;
  helpKey?: LabelKey;
  /** Marks the label with the required sign (*); the form says once what it means. */
  required?: boolean;
  /** Gets the field's own value type (a boolean field's `value` is a boolean). */
  render: (field: ControllerRenderProps<T, N> & { id: string }) => ReactElement;
}

/**
 * One form field: Ant Design label + control + the field's error shown inline under it,
 * translated (CLAUDE.md rule d), whether it came from Zod or from the API.
 */
export function FormField<T extends FieldValues, N extends Path<T> = Path<T>>({
  control,
  name,
  labelKey,
  helpKey,
  required = false,
  render,
}: FormFieldProps<T, N>) {
  const t = useLabels();
  const id = `field-${name}`;
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => {
        const message = parseFieldMessage(fieldState.error?.message);
        return (
          <Form.Item
            label={t(labelKey)}
            htmlFor={id}
            required={required}
            validateStatus={message === null ? undefined : 'error'}
            help={
              message === null ? (
                helpKey === undefined ? undefined : (
                  t(helpKey)
                )
              ) : (
                <span role="alert" data-testid={`error-${name}`}>
                  {t(message.key, message.params as LabelParams)}
                </span>
              )
            }
          >
            {render({ ...field, id })}
          </Form.Item>
        );
      }}
    />
  );
}
