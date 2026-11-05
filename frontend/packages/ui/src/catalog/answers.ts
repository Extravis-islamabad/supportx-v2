import type { CatalogQuestion } from '@supportx/api-client';

// Catalog form answers (WP-031 plan D6): the values the API takes, per question kind.

export type QuestionValue = string | number | boolean | string[] | null;

export const TEXT_MAX = 2000;
export const LONG_TEXT_MAX = 10_000;

/** A per-language text in `locale`, English when missing (plan D5). */
export function textIn(texts: Record<string, string> | undefined, locale: string): string {
  const own = texts?.[locale];
  return own !== undefined && own !== '' ? own : (texts?.en ?? '');
}

/** The questions a requester answers, in order (the others are for technicians or approvers). */
export function requesterQuestions(questions: CatalogQuestion[]): CatalogQuestion[] {
  return questions.filter((q) => (q.shown_to ?? ['requester']).includes('requester'));
}

/** The form's starting answers: each question's default, if any. */
export function startingAnswers(questions: CatalogQuestion[]): Record<string, QuestionValue> {
  return Object.fromEntries(
    questions
      .filter((q) => q.default !== undefined && q.default !== null)
      .map((q) => [q.key, q.default as QuestionValue]),
  );
}

/** The answers as sent: empty values left out, so a blank optional question sends nothing. */
export function sentAnswers(answers: Record<string, QuestionValue>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(answers).filter(
      ([, v]) => v !== null && v !== '' && !(Array.isArray(v) && v.length === 0),
    ),
  );
}
