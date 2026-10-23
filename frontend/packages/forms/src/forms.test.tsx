import { act, render, renderHook, screen } from '@testing-library/react';
import { Form, Input } from 'antd';
import { useForm } from 'react-hook-form';
import { describe, expect, it } from 'vitest';

import { ApiError } from '@supportx/api-client';
import { problem } from '@supportx/api-client/testing';
import { LabelsProvider } from '@supportx/labels';

import { FormField } from './FormField';
import { applyServerErrors, formFieldOf, parseFieldMessage } from './serverErrors';

const validation = new ApiError(
  422,
  problem(422, 'validation_failed', {
    errors: [
      {
        field: 'body.time_zone',
        code: 'invalid_choice',
        message_key: 'errors.field.invalid_choice',
        params: {},
      },
      {
        field: 'body.signature',
        code: 'value_too_long',
        message_key: 'errors.field.value_too_long',
        params: { max_length: 2000 },
      },
      {
        field: 'query.limit',
        code: 'out_of_range',
        message_key: 'errors.field.out_of_range',
        params: {},
      },
    ],
  }),
  null,
);

describe('server field errors', () => {
  it('maps body.<field> onto form fields and ignores the rest', () => {
    const { result } = renderHook(() => useForm<{ signature: string; time_zone: string }>());
    let applied = false;
    act(() => {
      applied = applyServerErrors(validation, result.current.setError, ['signature', 'time_zone']);
    });
    expect(applied).toBe(true);
    expect(parseFieldMessage(result.current.getFieldState('time_zone').error?.message)).toEqual({
      key: 'errors.field.invalid_choice',
      params: {},
    });
    expect(
      parseFieldMessage(result.current.getFieldState('signature').error?.message)?.params,
    ).toEqual({
      max_length: 2000,
    });
    expect(formFieldOf('query.limit')).toBe('query.limit');
  });

  it('is a no-op for errors without field errors', () => {
    const { result } = renderHook(() => useForm<{ signature: string }>());
    expect(applyServerErrors(new Error('x'), result.current.setError, ['signature'])).toBe(false);
    expect(
      applyServerErrors(
        new ApiError(409, problem(409, 'version_conflict'), null),
        result.current.setError,
        ['signature'],
      ),
    ).toBe(false);
  });

  it('shows the translated message inline under the field', () => {
    function Harness() {
      const form = useForm<{ time_zone: string }>({ defaultValues: { time_zone: 'Mars/Base' } });
      return (
        <LabelsProvider locale="ar">
          <Form>
            <FormField
              control={form.control}
              name="time_zone"
              labelKey="profile.time_zone"
              render={(field) => <Input {...field} />}
            />
          </Form>
          <button
            onClick={() => {
              applyServerErrors(validation, form.setError, ['time_zone']);
            }}
          >
            go
          </button>
        </LabelsProvider>
      );
    }
    render(<Harness />);
    act(() => {
      screen.getByRole('button').click();
    });
    expect(screen.getByTestId('error-time_zone').textContent).toBe(
      'هذه ليست إحدى القيم المسموح بها.',
    );
    expect(screen.getByLabelText('المنطقة الزمنية')).toBeDefined();
  });
});
