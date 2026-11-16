// Chip colours (the prototype's, D-158). Each pair reaches 4.5:1; the meaning is also in the
// words, never in the colour alone.
export interface Tone {
  bg: string;
  fg: string;
}

export const TONES = {
  danger: { bg: '#FEE4E2', fg: '#B42318' },
  orange: { bg: '#FFEAD5', fg: '#B93815' },
  info: { bg: '#EFF8FF', fg: '#175CD3' },
  neutral: { bg: '#F2F4F7', fg: '#475467' },
  warning: { bg: '#FEF0C7', fg: '#93370D' },
  progress: { bg: '#FFFAEB', fg: '#B54708' },
  success: { bg: '#ECFDF3', fg: '#067647' },
  brand: { bg: '#F4EBFF', fg: '#6B33B8' },
} as const satisfies Record<string, Tone>;

export function priorityTone(priority: string): Tone {
  switch (priority) {
    case 'p1':
      return TONES.danger;
    case 'p2':
      return TONES.orange;
    case 'p3':
      return TONES.info;
    default:
      return TONES.neutral;
  }
}

export function statusCategoryTone(category: string): Tone {
  switch (category) {
    case 'open':
      return TONES.info;
    case 'paused':
      return TONES.neutral;
    case 'resolved':
      return TONES.success;
    default:
      return TONES.neutral;
  }
}

export function portalStatusTone(status: string): Tone {
  switch (status) {
    case 'received':
      return TONES.brand;
    case 'in_progress':
      return TONES.progress;
    case 'waiting_for_you':
    case 'awaiting_approval':
      return TONES.warning;
    case 'resolved':
      return TONES.success;
    case 'rejected':
      return TONES.danger;
    default:
      return TONES.neutral;
  }
}
