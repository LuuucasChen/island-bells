"""动物森友会经典角色名 & 岛屿名 随机生成器"""

import random
from typing import Optional

# 动森 NPC 角色名
CHARACTER_NAMES = [
    # 常驻/基础服务NPC
    "狸克", "豆狸", "粒狸", "西施惠", "傅达",
    "麻儿", "娟儿", "莫里", "陆德里",
    # 特殊访客NPC
    "曹卖", "K.K.", "俞司廷", "龙克斯", "幽幽",
    "骆岚", "然然", "薛革", "狐利", "吕游",
    "傅珂", "巴猎", "里赛特先生",
    # 其他功能性NPC
    "托塔可可", "电源叔叔",
]

# 素材岛名（动森随机岛屿类型）
ISLAND_NAMES = [
    "普通岛", "竹林岛", "奇花岛", "背鳍鱼岛", "矛尾鱼岛",
    "蝴蝶锦鲤岛", "岩钱岛", "垃圾岛", "狼蛛岛", "蝎子岛",
    "金钱岛", "水果特產岛",
]


def get_random_island_name() -> str:
    """随机返回一个岛屿名"""
    return random.choice(ISLAND_NAMES)


def get_random_character_name(used_names: Optional[list[str]] = None) -> str:
    """
    随机返回一个角色名，排除已使用的名字
    如果所有名字都被占用了，则在名字后追加数字后缀
    """
    used = set(used_names or [])
    available = [n for n in CHARACTER_NAMES if n not in used]
    if available:
        return random.choice(available)
    # 所有名字都被占用，加后缀
    base = random.choice(CHARACTER_NAMES)
    for i in range(2, 100):
        candidate = f"{base}{i}"
        if candidate not in used:
            return candidate
    return f"{base}{random.randint(100, 999)}"
