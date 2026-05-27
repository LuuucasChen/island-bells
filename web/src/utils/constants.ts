/**
 * 岛屿铃钱记 — 常量配置
 */

/** 铃钱预设选项 */
export const CHIP_PRESETS = [
  { label: '1,000', value: 1000 },
  { label: '5,000', value: 5000 },
  { label: '10,000', value: 10000 },
  { label: '20,000', value: 20000 },
  { label: '50,000', value: 50000 },
]

/** 盲注预设选项 */
export const BLIND_PRESETS = [
  { label: '10/20', sb: 10, bb: 20 },
  { label: '25/50', sb: 25, bb: 50 },
  { label: '50/100', sb: 50, bb: 100 },
  { label: '100/200', sb: 100, bb: 200 },
]

/** 快捷追加金额 */
export const QUICK_AMOUNTS = [50, 100, 200, 500]

/** 最大玩家数 */
export const MAX_PLAYERS = 9

/** 座位号范围 */
export const SEAT_NUMBERS = Array.from({ length: MAX_PLAYERS }, (_, i) => i)

/** 动森角色名池（用于随机昵称） */
export const CHARACTER_NAMES = [
  '狸克', '西施惠', 'K.K.', '豆狸', '粒狸',
  '傅达', '傅珂', '绢儿', '麻儿', '棉儿',
  '吕游', '龙克斯', '鱼加', '裁缝姐姐', '狸猫',
  '小润', '美玲', '杰克', '小动', '彭花',
  '阿波罗', '阿一', '阿四', '星薇', '卜白',
  '恰姆', '罗宾', '樱桃', '佩利', '蒙奇',
  '草莓', '可可', '德式', '小酒窝', '彩虹',
]

/** 岛屿名池（用于随机房间名） */
export const ISLAND_NAMES = [
  '星星碎片岛', '铃钱岛', '摇钱树岛', '果实岛', '贝壳沙滩岛',
  '流星许愿岛', '萤火虫岛', '彩虹岛', '椰子岛', '竹子岛',
  '花园岛', '枫叶岛', '雪花岛', '樱花岛', '月光岛',
  '朝阳岛', '微风岛', '海浪岛', '星梦岛', '暖风岛',
  '甜蜜岛', '棉花岛', '蘑菇岛', '矿石岛', '化石岛',
  '蝴蝶岛', '独角仙岛', '鲈鱼岛', '大头菜岛', '狼蛛岛',
]

/** 随机取一个角色名（排除已用） */
export function getRandomCharacterName(usedNames: string[] = []): string {
  const used = new Set(usedNames)
  const available = CHARACTER_NAMES.filter((n) => !used.has(n))
  if (available.length > 0) {
    return available[Math.floor(Math.random() * available.length)]
  }
  const base = CHARACTER_NAMES[Math.floor(Math.random() * CHARACTER_NAMES.length)]
  return `${base}${Math.floor(Math.random() * 99) + 2}`
}

/** 随机取一个岛屿名 */
export function getRandomIslandName(): string {
  return ISLAND_NAMES[Math.floor(Math.random() * ISLAND_NAMES.length)]
}