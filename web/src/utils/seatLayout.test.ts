import { describe, it, expect } from 'vitest'
import { getSeatLayout, getTableScale } from './seatLayout'

describe('getSeatLayout - 座位分配算法', () => {
  it('2人: top1 left0 right0 me1', () => {
    const layout = getSeatLayout(2)
    expect(layout).toEqual({ leftCount: 0, topCount: 1, rightCount: 0, total: 2 })
  })

  it('3人: top2 left0 right0 me1', () => {
    const layout = getSeatLayout(3)
    expect(layout).toEqual({ leftCount: 0, topCount: 2, rightCount: 0, total: 3 })
  })

  it('4人: top1 left1 right1 me1', () => {
    const layout = getSeatLayout(4)
    expect(layout).toEqual({ leftCount: 1, topCount: 1, rightCount: 1, total: 4 })
  })

  it('5人: top2 left1 right1 me1', () => {
    const layout = getSeatLayout(5)
    expect(layout).toEqual({ leftCount: 1, topCount: 2, rightCount: 1, total: 5 })
  })

  it('6人: top3 left1 right1 me1', () => {
    const layout = getSeatLayout(6)
    expect(layout).toEqual({ leftCount: 1, topCount: 3, rightCount: 1, total: 6 })
  })

  it('7人: top2 left2 right2 me1', () => {
    const layout = getSeatLayout(7)
    expect(layout).toEqual({ leftCount: 2, topCount: 2, rightCount: 2, total: 7 })
  })

  it('8人: top3 left2 right2 me1', () => {
    const layout = getSeatLayout(8)
    expect(layout).toEqual({ leftCount: 2, topCount: 3, rightCount: 2, total: 8 })
  })

  it('9人: top4 left2 right2 me1', () => {
    const layout = getSeatLayout(9)
    expect(layout).toEqual({ leftCount: 2, topCount: 4, rightCount: 2, total: 9 })
  })

  it('各人数总和等于总玩家数减1(不含自己)', () => {
    for (let total = 2; total <= 9; total++) {
      const { leftCount, topCount, rightCount } = getSeatLayout(total)
      expect(leftCount + topCount + rightCount).toBe(total - 1)
    }
  })
})

describe('getTableScale - 响应式缩放', () => {
  it('顶部 < 5 人不缩放', () => {
    expect(getTableScale(1)).toBe(1)
    expect(getTableScale(2)).toBe(1)
    expect(getTableScale(3)).toBe(1)
    expect(getTableScale(4)).toBe(1)
  })

  it('顶部 5 人缩放至 0.84', () => {
    expect(getTableScale(5)).toBeCloseTo(0.84)
  })

  it('顶部 6 人缩放至 0.72 (下限)', () => {
    expect(getTableScale(6)).toBeCloseTo(0.72)
  })

  it('缩放比例始终 >= 0.72', () => {
    for (let i = 1; i <= 10; i++) {
      expect(getTableScale(i)).toBeGreaterThanOrEqual(0.72)
    }
  })
})
