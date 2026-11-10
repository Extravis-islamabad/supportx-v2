import { act, fireEvent, renderHook, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { renderUi } from '../test/render';
import { SettingsCard } from './SettingsCard';
import { StickySaveBar } from './StickySaveBar';
import { useSettingsDraft } from './useSettingsDraft';

// D-147 template E: grouped cards edit one draft; one save bar counts and saves the changes.
describe('template E (settings page)', () => {
  it('counts only the fields that differ, sends only those, and discards to what is saved', () => {
    const saved = { name: 'IT', days: 30, tags: ['a'] };
    const { result } = renderHook(() => useSettingsDraft(saved));
    expect(result.current.changes).toBe(0);
    act(() => {
      result.current.set({ name: 'IT desk', days: 30 });
    });
    expect(result.current.changes).toBe(1); // days is unchanged
    expect(result.current.changed).toEqual({ name: 'IT desk' });
    expect(result.current.draft).toEqual({ name: 'IT desk', days: 30, tags: ['a'] });
    act(() => {
      result.current.set({ tags: ['a'] }); // the same list again: no change
    });
    expect(result.current.changes).toBe(1);
    act(() => {
      result.current.discard();
    });
    expect(result.current.changes).toBe(0);
    expect(result.current.draft).toEqual(saved);
  });

  it('follows a save that lands: the saved values now hold the edit, nothing is left to save', () => {
    let saved = { name: 'IT', days: 30 };
    const { result, rerender } = renderHook(() => useSettingsDraft(saved));
    act(() => {
      result.current.set({ name: 'IT desk', days: 60 });
    });
    saved = { name: 'IT desk', days: 30 }; // only the name was saved (someone else kept days)
    rerender();
    expect(result.current.changed).toEqual({ days: 60 });
  });

  it('shows one save bar only while there are changes; no button inside a card', () => {
    const onSave = vi.fn();
    const { unmount } = renderUi(
      <>
        <SettingsCard title="Retention" testId="card">
          <input aria-label="Days" />
        </SettingsCard>
        <StickySaveBar changes={0} onDiscard={() => undefined} onSave={onSave} />
      </>,
    );
    expect(screen.queryByTestId('settings-save-bar')).toBeNull();
    expect(screen.getByTestId('card').querySelector('button')).toBeNull();
    unmount();
    renderUi(<StickySaveBar changes={2} onDiscard={() => undefined} onSave={onSave} />);
    expect(screen.getByTestId('settings-save-bar').textContent).toContain('2');
    fireEvent.click(screen.getByTestId('settings-save'));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it('says why Save cannot be used yet, and disables it with that reason', () => {
    renderUi(
      <StickySaveBar
        changes={1}
        whyNot="Images are being checked."
        onDiscard={() => undefined}
        onSave={() => undefined}
      />,
    );
    const save = screen.getByTestId<HTMLButtonElement>('settings-save');
    expect(save.disabled).toBe(true);
    expect(save.getAttribute('aria-describedby')).toBe('settings-save-why');
    expect(screen.getByTestId('settings-save-why').textContent).toBe('Images are being checked.');
  });
});
