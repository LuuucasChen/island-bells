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

/** 动森角色名池（仅保留有头像图片的角色） */
export const CHARACTER_NAMES = [
  '狸克', '豆狸', '粒狸', '西施惠', '傅达',
  '麻儿', '娟儿', '莫里', '陆德里', '曹卖',
  'KK', '俞司廷', '龙克斯', '幽幽', '骆岚',
  '然然', '薛革', '狐利', '吕游', '傅珂',
  '巴猎', '里赛特先生', '杰克',
]

/** 角色昵称 → 头像文件名映射 */
export const CHARACTER_AVATAR_MAP: Record<string, string> = {
  '狸克': 'Tom_Nook_狸克.png',
  '豆狸': 'Nookling_豆狸粒狸.png',
  '粒狸': 'Nookling_豆狸粒狸.png',
  '西施惠': 'Isabelle_西施惠.png',
  '傅达': 'Blathers_傅达.png',
  '麻儿': 'Sable_麻儿.png',
  '娟儿': 'Mabel_娟儿.png',
  '莫里': 'Orville_莫里.png',
  '陆德里': 'Wilbur_陆德里.png',
  '曹卖': 'Daisy_Mae_曹卖.png',
  'KK': 'KK_Slider.png',
  '俞司廷': 'CJ_俞司廷.png',
  '龙克斯': 'Flick_龙克斯.png',
  '幽幽': 'Wisp_幽幽.png',
  '骆岚': 'Saharah_骆岚.png',
  '然然': 'Leif_然然.png',
  '薛革': 'Kicks_薛革.png',
  '狐利': 'Redd_狐利.png',
  '吕游': 'Gulliver_吕游.png',
  '傅珂': 'Celeste_傅珂.png',
  '巴猎': 'Harvey_巴猎.png',
  '里赛特先生': 'Resetti_里赛特先生.png',
  '杰克': 'Jack.png',
}

/** 获取角色头像 URL，无匹配返回 null */
export function getCharacterAvatar(name: string): string | null {
  const file = CHARACTER_AVATAR_MAP[name]
  return file ? `/characters/${file}` : null
}

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