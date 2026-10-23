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

export interface FormFieldProps<T extends FieldValues> {
  control: Control<T>;
  name: Path<T>;
  labelKey: LabelKey;
  helpKey?: LabelKey;
  render: (field: ControllerRenderProps<T, Path<T>> & { id: string }) => ReactElement;
}

/**
 * One form field: Ant Design label + control + the field's error shown inline under it,
 * translated (CLAUDE.md rule d), whether it came from Zod or from the API.
 */
export function FormField<T extends FieldValues>({
  control,
  name,
  labelKey,
  helpKey,
  render,
}: FormFieldProps<T>) {
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
