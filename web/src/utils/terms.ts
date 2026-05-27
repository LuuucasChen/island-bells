/**
 * 岛屿铃钱记 — 铃钱体系术语映射 (TypeScript 版)
 *
 * 后端 API 使用技术术语 (chips/bet/blind 等)
 * 前端展示层使用铃钱体系术语
 *
 * 所有用户可见文案必须通过此模块映射，禁止硬编码扑克术语
 */

// 动作术语映射
export const ACTION_TERMS: Record<string, string> = {
  blind: '费用',
  call: '跟随',
  raise: '追加',
  allin: '满仓',
  fold: '休息',
}

// 动作术语映射 (带金额模板)
export const ACTION_TERMS_WITH_AMOUNT: Record<string, string> = {
  blind: '{amount} 铃钱',
  call: '跟随 {amount}',
  raise: '追加 {amount}',
  allin: '满仓 {amount}',
  fold: '休息',
}

// 轮次/阶段术语映射
export const ROUND_TERMS: Record<string, string> = {
  preflop: '早晨',
  flop: '午后',
  turn: '傍晚',
  river: '夜晚',
  showdown: '收获祭',
}

// 轮次图标映射
export const ROUND_ICONS: Record<string, string> = {
  preflop: '☀️',
  flop: '🌤',
  turn: '🌅',
  river: '🌙',
  showdown: '🎉',
}

// 核心概念术语
export const CONCEPT_TERMS: Record<string, string> = {
  chips: '铃钱',
  room: '岛屿',
  roomCode: '渡渡鸟码',
  dealer: '岛主',
  smallBlind: '树苗费',
  bigBlind: '大树费',
  pot: '收获篮',
  sidePot: '副收获篮',
  hand: '一季',
  rebuy: '补给',
  settle: '收获',
  sit: '登岛',
  stand: '离岛',
  bet: '投入',
}

// 角色徽章术语
export const ROLE_TERMS: Record<string, string> = {
  D: 'D',
  SB: '🌱',
  BB: '🌳',
}

// 房间状态术语
export const ROOM_STATUS_TERMS: Record<string, string> = {
  waiting: '等待登岛',
  playing: '游戏中',
  finished: '已结束',
}

// 手牌状态术语
export const HAND_STATUS_TERMS: Record<string, string> = {
  betting: '投入中',
  settling: '收获中',
  settled: '已收获',
}

// 玩家状态术语
export const PLAYER_STATUS_TERMS: Record<string, string> = {
  active: '在岛',
  folded: '休息中',
  allin: '满仓',
  disconnected: '离线',
  busted: '铃钱耗尽',
}

/** 格式化铃钱显示 (千分位) */
export function formatBells(amount: number | null): string {
  if (amount === null || amount === undefined) return '0'
  return amount.toLocaleString()
}

/** 格式化铃钱显示 (带图标) */
export function formatBellsWithIcon(amount: number | null): string {
  return `🔔 ${formatBells(amount)}`
}

/** 获取动作显示文案 */
export function getActionText(action: string, amount?: number): string {
  if (amount !== undefined && amount !== null) {
    const template = ACTION_TERMS_WITH_AMOUNT[action] || action
    return template.replace('{amount}', formatBells(amount))
  }
  return ACTION_TERMS[action] || action
}

/** 获取阶段显示文案 */
export function getRoundText(round: string): string {
  return ROUND_TERMS[round] || round
}

/** 获取阶段图标 */
export function getRoundIcon(round: string): string {
  return ROUND_ICONS[round] || ''
}

/** 获取阶段完整文案 (图标 + 文字) */
export function getRoundFullText(round: string): string {
  return `${getRoundIcon(round)} ${getRoundText(round)}`
}