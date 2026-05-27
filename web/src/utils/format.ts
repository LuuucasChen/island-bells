/**
 * 岛屿铃钱记 — 格式化工具
 */

/** 格式化铃钱数量 (千分位逗号) */
export function formatBells(amount: number): string {
  return amount.toLocaleString()
}

/** 格式化铃钱带铃钱图标 */
export function formatBellsIcon(amount: number): string {
  return `🔔 ${formatBells(amount)}`
}

/** 格式化日期 */
export function formatDate(dateStr: string | null): string {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}