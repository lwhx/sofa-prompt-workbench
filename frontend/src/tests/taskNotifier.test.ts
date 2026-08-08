import { describe, expect, it } from 'vitest'
import { detectCompletedTransitions } from '@/composables/useTaskNotifier'
import type { RowItem } from '@/stores/rows'

/** 构造最小 RowItem 测试数据。 */
function makeRow(id: string, status: string, name: string = id): RowItem {
  return {
    id, name, status, row_revision: 1, results_count: 0,
    sort_key: 0, auto_run: false, created_at: null,
  }
}

describe('detectCompletedTransitions', () => {
  it('detects transition from QUEUED to COMPLETED', () => {
    const prev = new Map([['r1', 'QUEUED']])
    const current = [makeRow('r1', 'COMPLETED', '沙发A')]
    const result = detectCompletedTransitions(prev, current)
    expect(result).toHaveLength(1)
    expect(result[0]).toEqual({ id: 'r1', name: '沙发A', status: 'COMPLETED' })
  })

  it('detects transition from ANALYZING to FAILED', () => {
    const prev = new Map([['r2', 'ANALYZING']])
    const current = [makeRow('r2', 'FAILED', '沙发B')]
    const result = detectCompletedTransitions(prev, current)
    expect(result).toHaveLength(1)
    expect(result[0].status).toBe('FAILED')
  })

  it('detects transition from VALIDATING to NEEDS_REVIEW', () => {
    const prev = new Map([['r3', 'VALIDATING']])
    const current = [makeRow('r3', 'NEEDS_REVIEW')]
    const result = detectCompletedTransitions(prev, current)
    expect(result).toHaveLength(1)
    expect(result[0].status).toBe('NEEDS_REVIEW')
  })

  it('does not detect transition to READY (not a completion state)', () => {
    const prev = new Map([['r1', 'QUEUED']])
    const current = [makeRow('r1', 'READY')]
    const result = detectCompletedTransitions(prev, current)
    expect(result).toHaveLength(0)
  })

  it('does not detect when status was already terminal', () => {
    const prev = new Map([['r1', 'COMPLETED']])
    const current = [makeRow('r1', 'COMPLETED')]
    const result = detectCompletedTransitions(prev, current)
    expect(result).toHaveLength(0)
  })

  it('does not detect transition from non-active state', () => {
    const prev = new Map([['r1', 'READY']])
    const current = [makeRow('r1', 'COMPLETED')]
    const result = detectCompletedTransitions(prev, current)
    expect(result).toHaveLength(0)
  })

  it('handles multiple transitions simultaneously', () => {
    const prev = new Map([
      ['r1', 'QUEUED'],
      ['r2', 'ANALYZING'],
      ['r3', 'VALIDATING'],
    ])
    const current = [
      makeRow('r1', 'COMPLETED', 'A'),
      makeRow('r2', 'FAILED', 'B'),
      makeRow('r3', 'NEEDS_REVIEW', 'C'),
    ]
    const result = detectCompletedTransitions(prev, current)
    expect(result).toHaveLength(3)
  })

  it('handles empty current rows', () => {
    const prev = new Map([['r1', 'QUEUED']])
    const result = detectCompletedTransitions(prev, [])
    expect(result).toHaveLength(0)
  })
})
