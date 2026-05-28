/**
 * 扑克桌环形座位分配算法
 * 德州扑克顺时针: 我(底部) → 左侧 → 上侧 → 右侧
 */

export interface SeatLayout {
  leftCount: number
  topCount: number
  rightCount: number
  /** 总人数(含自己) */
  total: number
}

/**
 * 根据总玩家数计算各区域座位分配
 * @param totalPlayers 总玩家数(含自己), 2-9
 */
export function getSeatLayout(totalPlayers: number): SeatLayout {
  const n = Math.max(0, totalPlayers - 1) // 其他人数量
  // 4+人(n>=3)时左右各1人，7+人(n>=6)时左右各2人，剩余去顶部
  const leftCount = n < 3 ? 0 : n < 6 ? 1 : 2
  const rightCount = n < 3 ? 0 : n < 6 ? 1 : 2
  const topCount = Math.max(0, n - leftCount - rightCount)
  return { leftCount, topCount, rightCount, total: totalPlayers }
}

/**
 * 计算响应式缩放比例
 * 顶部 >= 5 人时等比缩小
 */
export function getTableScale(topCount: number): number {
  return topCount >= 5 ? Math.max(0.72, 4.2 / topCount) : 1
}
