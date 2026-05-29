"""房间活跃度跟踪器：记录每个房间最后一次玩家行动时间，用于死牌局自动清理。

仅在内存中维护映射，服务重启后计时器重置（以重启时间为新起点）。
"""

from datetime import datetime, timezone
from typing import Dict, Optional

# 房间最后一次玩家下注行动的时间 (UTC)
_room_last_action: Dict[int, datetime] = {}


def touch(room_id: int) -> None:
    """记录房间最后一次玩家行动的时间戳"""
    _room_last_action[room_id] = datetime.now(timezone.utc)


def get(room_id: int) -> Optional[datetime]:
    """获取房间最后一次行动时间，未记录则返回 None"""
    return _room_last_action.get(room_id)


def remove(room_id: int) -> None:
    """从跟踪表中移除房间记录（房间结束 / 已被清理）"""
    _room_last_action.pop(room_id, None)


def snapshot() -> Dict[int, datetime]:
    """返回当前跟踪表的快照副本，供后台扫描遍历使用"""
    return dict(_room_last_action)
