import { describe, expect, it } from 'vitest';
import {
  LEARN_STARTER_QUESTION_POOL,
  OPS_STARTER_QUESTION_POOL,
  starterQuestionPoolForMode,
} from './workspaceStarterQuestions';

describe('starterQuestionPoolForMode', () => {
  it('keeps ops and learn starter questions distinct', () => {
    expect(starterQuestionPoolForMode('ops')).toBe(OPS_STARTER_QUESTION_POOL);
    expect(starterQuestionPoolForMode('learn')).toBe(LEARN_STARTER_QUESTION_POOL);
    expect(new Set(OPS_STARTER_QUESTION_POOL)).toHaveLength(OPS_STARTER_QUESTION_POOL.length);
    expect(new Set(LEARN_STARTER_QUESTION_POOL)).toHaveLength(LEARN_STARTER_QUESTION_POOL.length);
    expect(OPS_STARTER_QUESTION_POOL.some((question) => LEARN_STARTER_QUESTION_POOL.includes(question))).toBe(false);
  });

  it('makes learning mode ask conceptual learning-path questions', () => {
    expect(LEARN_STARTER_QUESTION_POOL.join('\n')).toContain('개념');
    expect(LEARN_STARTER_QUESTION_POOL.join('\n')).toContain('학습');
    expect(OPS_STARTER_QUESTION_POOL.join('\n')).toContain('점검');
  });

  it('keeps each starter pool aligned to its role intent', () => {
    const opsIntent = /(점검|확인|절차|검증|먼저|상태|운영자)/;
    const learnIntent = /(개념|학습|차이|순서|왜|처음|이해)/;
    const proceduralDrift = /(먼저 볼 절차|점검할 때|운영자가 먼저)/;

    expect(OPS_STARTER_QUESTION_POOL.every((question) => opsIntent.test(question))).toBe(true);
    expect(LEARN_STARTER_QUESTION_POOL.every((question) => learnIntent.test(question))).toBe(true);
    expect(LEARN_STARTER_QUESTION_POOL.some((question) => proceduralDrift.test(question))).toBe(false);
  });
});
