"""岛屿铃钱记 — 游戏引擎

核心职责:
1. 一季(Hand)状态机管理: preflop → flop → turn → river → showdown
2. 扑克牌发牌: 标准 52 张牌，每人 2 张手牌 + 5 张公共牌
3. 下注轮逻辑: 德州扑克行动顺序、校验合法性、推进轮次
4. 收获篮(Pot)计算: 主收获篮 + 副收获篮(边池)分层算法
5. 牌力评估: showdown 时自动比牌确定赢家
6. 岛主/树苗费/大树费自动轮转
"""

import json
from typing import Optional
from sqlalchemy.orm import Session

from app.models import Room, RoomPlayer, Hand, Bet, Pot, HandResult, Rebuy
from app.engine.deck import Deck, Card, cards_to_json, cards_from_json
from app.engine.evaluator import evaluate_hand, evaluate_all_players, compare_hands, get_hand_type_name
from app.utils import BadRequestException, ForbiddenException, NotFoundException


# ======================== 状态机 ========================

ROUND_ORDER = ["preflop", "flop", "turn", "river", "showdown"]

ROUND_NEXT = {
    "preflop": "flop",
    "flop": "turn",
    "turn": "river",
    "river": "showdown",
}


def next_round(current: str) -> Optional[str]:
    """获取下一个阶段，showdown 之后返回 None"""
    return ROUND_NEXT.get(current)


# ======================== 座位/角色轮转 ========================

def get_active_seated_players(db: Session, room_id: int) -> list[RoomPlayer]:
    """获取房间内已入座且活跃的玩家，按座位号排序"""
    return (
        db.query(RoomPlayer)
        .filter(
            RoomPlayer.room_id == room_id,
            RoomPlayer.is_active == 1,
            RoomPlayer.seat_number >= 0,
        )
        .order_by(RoomPlayer.seat_number)
        .all()
    )


def rotate_dealer(seat_numbers: list[int], current_dealer_seat: int) -> int:
    """庄位顺时针轮转，返回下一个庄家座位号"""
    if not seat_numbers:
        return current_dealer_seat
    sorted_seats = sorted(seat_numbers)
    if current_dealer_seat not in sorted_seats:
        return sorted_seats[0]
    idx = sorted_seats.index(current_dealer_seat)
    return sorted_seats[(idx + 1) % len(sorted_seats)]


def assign_positions(seat_numbers: list[int], dealer_seat: int) -> dict:
    """
    根据庄家座位号分配角色位置
    返回: {dealer_seat, sb_seat, bb_seat}

    2人: 庄家=SB, 另一人=BB
    3人+: 庄家下一位=SB, 再下一位=BB
    """
    sorted_seats = sorted(seat_numbers)
    n = len(sorted_seats)

    if n < 2:
        raise BadRequestException("至少需要2名已入座玩家才能开始")

    dealer_idx = sorted_seats.index(dealer_seat) if dealer_seat in sorted_seats else 0

    if n == 2:
        # Heads-up: 庄家=SB
        sb_seat = dealer_seat
        bb_seat = sorted_seats[(dealer_idx + 1) % n]
    else:
        sb_seat = sorted_seats[(dealer_idx + 1) % n]
        bb_seat = sorted_seats[(dealer_idx + 2) % n]

    return {"dealer_seat": dealer_seat, "sb_seat": sb_seat, "bb_seat": bb_seat}


def get_action_order(seat_numbers: list[int], dealer_seat: int, current_round: str) -> list[int]:
    """
    获取当前阶段的行动顺序（座位号列表）

    早晨(preflop): BB之后的那位先行动 (UTG)，最后到 BB
    午后/傍晚/夜晚: SB 先行动 (或庄家后第一个)，最后到庄家
    """
    sorted_seats = sorted(seat_numbers)
    n = len(sorted_seats)
    if n == 0:
        return []

    dealer_idx = sorted_seats.index(dealer_seat) if dealer_seat in sorted_seats else 0

    if current_round == "preflop":
        # UTG = BB 后一位
        if n == 2:
            # Heads-up: SB(=庄家)先行动
            bb_idx = (dealer_idx + 1) % n
            start_idx = dealer_idx  # SB 先
        else:
            bb_idx = (dealer_idx + 2) % n
            start_idx = (bb_idx + 1) % n  # UTG
        order = []
        for i in range(n):
            order.append(sorted_seats[(start_idx + i) % n])
    else:
        # Post-flop: SB(庄家下一位)先行动
        if n == 2:
            # Heads-up: SB(=庄家)先行动
            start_idx = dealer_idx
        else:
            start_idx = (dealer_idx + 1) % n
        order = []
        for i in range(n):
            order.append(sorted_seats[(start_idx + i) % n])

    return order


# ======================== 下注校验 ========================

def validate_bet_action(
    action: str,
    amount: int,
    player_chips: int,
    player_bet_this_round: int,
    current_max_bet: int,
    min_raise: int,
) -> dict:
    """
    校验下注动作是否合法，返回 {valid, actual_amount}

    action: call / raise / allin / fold / check
    """
    to_call = current_max_bet - player_bet_this_round

    if action == "fold":
        return {"valid": True, "actual_amount": 0}

    if action == "check":
        # check 只在无需跟注时合法
        if to_call > 0:
            return {"valid": False, "actual_amount": 0, "reason": f"当前需要跟注 {to_call}，无法过牌"}
        return {"valid": True, "actual_amount": 0}

    if action == "call":
        if to_call <= 0:
            # 已经是当前最高注，视为 check
            return {"valid": True, "actual_amount": 0}
        actual = min(to_call, player_chips)
        return {"valid": True, "actual_amount": actual}

    if action == "raise":
        if amount <= 0:
            return {"valid": False, "actual_amount": 0, "reason": "追加金额必须大于0"}
        # raise 总额必须 >= 当前最高注 + 最小加注额
        total_bet = player_bet_this_round + amount
        if total_bet < current_max_bet + min_raise and amount < player_chips:
            # 不是 allin 的情况，必须满足最小加注
            return {"valid": False, "actual_amount": 0, "reason": f"追加金额不足，最少需要 {current_max_bet + min_raise - player_bet_this_round}"}
        actual = min(amount, player_chips)
        return {"valid": True, "actual_amount": actual}

    if action == "allin":
        return {"valid": True, "actual_amount": player_chips}

    return {"valid": False, "actual_amount": 0, "reason": f"未知动作: {action}"}


# ======================== 收获篮(Pot)计算 ========================

def calculate_pots(bets: list[dict]) -> list[dict]:
    """
    副收获篮(边池)分层计算算法

    输入: [{player_id, total_bet}] — 每位玩家本季总投入
    输出: [{pot_type, pot_level, amount, eligible_player_ids}]

    算法:
    1. 将所有玩家的总投入按升序排列并去重
    2. 逐层计算: 每层 = (当前层投入 - 上一层投入) × 符合资格的玩家数
    3. 符合资格的玩家 = 投入 >= 当前层投入额的玩家 (排除已 fold 的)
    """
    if not bets:
        return []

    # 按总投入升序排列
    sorted_bets = sorted(bets, key=lambda b: b["total_bet"])
    # 去重投入层级
    levels = sorted(set(b["total_bet"] for b in sorted_bets if b["total_bet"] > 0))

    pots = []
    prev_level = 0

    for level in levels:
        # 投入 >= level 的玩家才有资格
        eligible = [b["player_id"] for b in sorted_bets if b["total_bet"] >= level]
        if not eligible:
            continue

        # 本层金额 = (level - prev_level) × 符合资格人数
        pot_amount = (level - prev_level) * len(eligible)

        if pot_amount > 0:
            pot_type = "main" if prev_level == 0 and len(pots) == 0 else "side"
            pots.append({
                "pot_type": pot_type,
                "pot_level": len(pots),
                "amount": pot_amount,
                "eligible_player_ids": eligible,
            })

        prev_level = level

    return pots


# ======================== 一季(Hand)流程 ========================

class HandEngine:
    """一季游戏引擎 — 封装一手牌的完整生命周期"""

    def __init__(self, db: Session, room: Room):
        self.db = db
        self.room = room

    def start_new_hand(self) -> Hand:
        """开始新一季"""
        all_seated = get_active_seated_players(self.db, self.room.id)
        # 过滤掉铃钱为 0 的玩家 (无法参与下注)
        players = [p for p in all_seated if p.chip_count > 0]
        if len(players) < 2:
            raise BadRequestException("至少需要2名铃钱大于0的已入座玩家")

        seat_numbers = [p.seat_number for p in players]

        # 轮转庄家 (确保庄家在可玩玩家中)
        current_dealer = self.room.dealer_seat
        if current_dealer not in seat_numbers:
            # 庄家铃钱为 0, 顺延到下一个有效座位
            current_dealer = seat_numbers[0]
        new_dealer_seat = rotate_dealer(seat_numbers, current_dealer)
        positions = assign_positions(seat_numbers, new_dealer_seat)

        # 更新房间庄位
        self.room.dealer_seat = new_dealer_seat

        # 计算本季编号
        last_hand = (
            self.db.query(Hand)
            .filter(Hand.room_id == self.room.id)
            .order_by(Hand.hand_number.desc())
            .first()
        )
        hand_number = (last_hand.hand_number + 1) if last_hand else 1

        # 查找角色对应的 player
        dealer_player = self._find_player_by_seat(players, positions["dealer_seat"])
        sb_player = self._find_player_by_seat(players, positions["sb_seat"])
        bb_player = self._find_player_by_seat(players, positions["bb_seat"])

        # 创建 Hand 记录
        hand = Hand(
            room_id=self.room.id,
            hand_number=hand_number,
            dealer_player_id=dealer_player.id,
            sb_player_id=sb_player.id,
            bb_player_id=bb_player.id,
            current_round="preflop",
            status="betting",
        )
        self.db.add(hand)
        self.db.flush()

        # === 发牌 ===
        deck = Deck()

        # 给每个玩家发 2 张手牌
        hole_cards_map = {}
        for p in players:
            cards = deck.deal(2)
            hole_cards_map[str(p.id)] = [c.to_dict() for c in cards]

        hand.hole_cards = json.dumps(hole_cards_map)
        hand.deck_state = deck.to_json()
        hand.community_cards = "[]"  # 暂无公共牌

        # 扣除 SB / BB
        sb_amount = min(self.room.sb_amount, sb_player.chip_count)
        bb_amount = min(self.room.bb_amount, bb_player.chip_count)

        sb_player.chip_count -= sb_amount
        bb_player.chip_count -= bb_amount

        # 记录盲注为 blind 动作
        self.db.add(Bet(
            hand_id=hand.id,
            player_id=sb_player.id,
            round="preflop",
            action="blind",
            amount=sb_amount,
        ))
        self.db.add(Bet(
            hand_id=hand.id,
            player_id=bb_player.id,
            round="preflop",
            action="blind",
            amount=bb_amount,
        ))

        hand.pot_total = sb_amount + bb_amount

        # 设置 preflop 首个行动玩家 (UTG = BB 后一位)
        action_order = get_action_order(seat_numbers, new_dealer_seat, "preflop")
        if action_order:
            first_actor = self._find_player_by_seat(players, action_order[0])
            hand.turn_player_id = first_actor.id

        self.db.commit()
        self.db.refresh(hand)

        return hand

    def place_bet(self, hand: Hand, player: RoomPlayer, action: str, amount: int = 0) -> Bet:
        """玩家投入铃钱 — 按德州扑克顺序下注"""
        if hand.status != "betting":
            raise BadRequestException("当前季节不在投入阶段")

        # 校验是否轮到该玩家
        if hand.turn_player_id and hand.turn_player_id != player.id:
            raise BadRequestException("还没轮到你行动")

        # 获取当前轮已有下注
        round_bets = (
            self.db.query(Bet)
            .filter(Bet.hand_id == hand.id, Bet.round == hand.current_round)
            .all()
        )

        # 计算当前轮每人的投入和最高注
        player_bets = {}
        for b in round_bets:
            player_bets[b.player_id] = player_bets.get(b.player_id, 0) + b.amount

        current_max_bet = max(player_bets.values()) if player_bets else 0
        my_bet = player_bets.get(player.id, 0)

        # 计算最小加注额 (默认 = BB)
        min_raise = self.room.bb_amount

        # 校验动作
        result = validate_bet_action(
            action=action,
            amount=amount,
            player_chips=player.chip_count,
            player_bet_this_round=my_bet,
            current_max_bet=current_max_bet,
            min_raise=min_raise,
        )

        if not result["valid"]:
            raise BadRequestException(result.get("reason", "非法操作"))

        actual_amount = result["actual_amount"]

        # 扣除铃钱
        player.chip_count -= actual_amount

        # 记录投入
        bet = Bet(
            hand_id=hand.id,
            player_id=player.id,
            round=hand.current_round,
            action=action,
            amount=actual_amount,
        )
        self.db.add(bet)

        # 更新收获篮总额
        hand.pot_total += actual_amount

        # 确保新 Bet 记录已写入 DB，_advance_turn 查询时能看到
        self.db.flush()

        # ===== 推进到下一个玩家 =====
        self._advance_turn(hand, player, action, actual_amount)

        # ===== 弃牌后自动结算 =====
        if action == "fold":
            self._check_auto_end(hand)

        self.db.commit()
        self.db.refresh(bet)

        return bet

    def _advance_turn(self, hand: Hand, acting_player: RoomPlayer, action: str, amount: int):
        """下注后推进到下一个行动玩家

        关键修复: 跟踪每个玩家是否已经行动过 (acted)。
        - 盲注 (blind) 不算作一次主动行动
        - 只有当所有可操作玩家都已行动且注额匹配时，本轮才结束
        - BB 在 preflop 有权 check/raise (option)
        """
        # 获取所有活跃入座玩家
        all_players = get_active_seated_players(self.db, hand.room_id)

        # 已 fold 的玩家
        folded_ids = {
            b.player_id for b in self.db.query(Bet)
            .filter(Bet.hand_id == hand.id, Bet.action == "fold")
            .all()
        }

        # 非 fold 的活跃玩家
        active_players = [p for p in all_players if p.id not in folded_ids]

        if len(active_players) <= 1:
            hand.turn_player_id = None
            return

        # 获取本轮所有下注记录
        round_bets = (
            self.db.query(Bet)
            .filter(Bet.hand_id == hand.id, Bet.round == hand.current_round)
            .all()
        )

        # 计算每人本轮投入
        player_bets = {}
        for b in round_bets:
            player_bets[b.player_id] = player_bets.get(b.player_id, 0) + b.amount
        current_max_bet = max(player_bets.values()) if player_bets else 0

        # 计算每个玩家是否已经主动行动过 (非 blind)
        acted_ids = set()
        for b in round_bets:
            if b.action != "blind":
                acted_ids.add(b.player_id)

        # 可操作玩家: 非 fold 且 chip_count > 0
        actionable_players = [p for p in active_players if p.chip_count > 0]

        if len(actionable_players) == 0:
            hand.turn_player_id = None
            return

        if len(actionable_players) == 1:
            p = actionable_players[0]
            if player_bets.get(p.id, 0) >= current_max_bet:
                hand.turn_player_id = None
                return
            hand.turn_player_id = p.id
            return

        # 多个可操作玩家: 检查是否所有人都已行动且跟平
        all_acted = all(p.id in acted_ids for p in actionable_players)
        all_matched = all(
            player_bets.get(p.id, 0) >= current_max_bet
            for p in actionable_players
        )

        if all_acted and all_matched:
            hand.turn_player_id = None
            return

        # 按德州扑克顺序找下一个行动玩家 (未行动 + 未跟平)
        seat_numbers = [p.seat_number for p in all_players]
        dealer = self.db.query(RoomPlayer).filter(RoomPlayer.id == hand.dealer_player_id).first()
        dealer_seat = dealer.seat_number if dealer else 0
        action_order = get_action_order(seat_numbers, dealer_seat, hand.current_round)

        try:
            current_seat = acting_player.seat_number
            current_idx = action_order.index(current_seat)
        except (ValueError, AttributeError):
            current_idx = -1

        for offset in range(1, len(action_order) + 1):
            next_seat = action_order[(current_idx + offset) % len(action_order)]
            next_player = self._find_player_by_seat(all_players, next_seat)
            if next_player.id in folded_ids:
                continue  # 已 fold
            if next_player.chip_count == 0:
                continue  # 已 all-in
            if next_player.id in acted_ids and player_bets.get(next_player.id, 0) >= current_max_bet:
                continue  # 已行动且已跟平
            hand.turn_player_id = next_player.id
            return

        hand.turn_player_id = None

    def _compute_last_aggressor(self, hand: Hand):
        """计算 showdown 时的最后激进者 (必须亮牌的玩家)

        规则:
        1. 从所有下注记录中找最后一个 raise/allin 的玩家
        2. 如果没有激进者 (全部 check/call)，取庄家后第一个存活玩家
        3. last_aggressor 自动加入 revealed_players (必须亮牌)
        """
        # 查找最后的 raise/allin (按时间倒序)
        last_aggro_bet = (
            self.db.query(Bet)
            .filter(
                Bet.hand_id == hand.id,
                Bet.action.in_(["raise", "allin"]),
            )
            .order_by(Bet.created_at.desc())
            .first()
        )

        if last_aggro_bet:
            hand.last_aggressor_id = last_aggro_bet.player_id
        else:
            # 无人激进: 庄家后第一个存活玩家自动亮牌
            all_players = get_active_seated_players(self.db, hand.room_id)
            all_bets = self.db.query(Bet).filter(Bet.hand_id == hand.id).all()
            folded_ids = {b.player_id for b in all_bets if b.action == "fold"}
            alive = [p for p in all_players if p.id not in folded_ids]

            if alive:
                seat_numbers = [p.seat_number for p in all_players]
                dealer = self.db.query(RoomPlayer).filter(
                    RoomPlayer.id == hand.dealer_player_id
                ).first()
                dealer_seat = dealer.seat_number if dealer else 0
                action_order = get_action_order(seat_numbers, dealer_seat, "flop")
                for seat in action_order:
                    p = self._find_player_by_seat(all_players, seat)
                    if p and p.id not in folded_ids:
                        hand.last_aggressor_id = p.id
                        break
                else:
                    hand.last_aggressor_id = alive[0].id

        # last_aggressor 自动加入 revealed_players
        if hand.last_aggressor_id:
            hand.revealed_players = str(hand.last_aggressor_id)

    def _check_auto_end(self, hand: Hand):
        """弃牌后检查：如果只剩 1 个存活玩家，自动发完公共牌并进入结算
        
        注意: fold 退款逻辑统一在 _calculate_pots_for_hand 中处理，
              这里只负责状态转换和补发公共牌。
        """
        all_players = get_active_seated_players(self.db, hand.room_id)
        all_bets = self.db.query(Bet).filter(Bet.hand_id == hand.id).all()
        folded_ids = {b.player_id for b in all_bets if b.action == "fold"}
        alive = [p for p in all_players if p.id not in folded_ids]

        if len(alive) <= 1:
            hand.turn_player_id = None

            # 标记: 因 fold 结束
            hand.ended_by_fold = 1

            # 发完所有剩余公共牌
            community = cards_from_json(hand.community_cards) if hand.community_cards else []
            deck = Deck.from_json(hand.deck_state) if hand.deck_state else Deck()
            while len(community) < 5:
                deck.burn(1)
                community.extend(deck.deal(1))
            hand.community_cards = cards_to_json(community)
            hand.deck_state = deck.to_json()

            hand.current_round = "showdown"
            hand.status = "settling"
            # _calculate_pots_for_hand 会自动处理 fold 退款
            self._calculate_pots_for_hand(hand)

    def advance_round(self, hand: Hand) -> Hand:
        """推进到下一阶段，并发公共牌"""
        if hand.status != "betting":
            raise BadRequestException("当前季节不在投入阶段")

        next_rnd = next_round(hand.current_round)
        if next_rnd is None:
            raise BadRequestException("已在收获祭阶段，无法继续推进")

        hand.current_round = next_rnd

        # 恢复牌堆并发公共牌
        deck = Deck.from_json(hand.deck_state) if hand.deck_state else Deck()
        community = cards_from_json(hand.community_cards) if hand.community_cards else []

        if next_rnd == "flop":
            deck.burn(1)
            community.extend(deck.deal(3))
        elif next_rnd == "turn":
            deck.burn(1)
            community.extend(deck.deal(1))
        elif next_rnd == "river":
            deck.burn(1)
            community.extend(deck.deal(1))

        hand.community_cards = cards_to_json(community)
        hand.deck_state = deck.to_json()

        if next_rnd == "showdown":
            hand.status = "settling"
            hand.turn_player_id = None
            self._compute_last_aggressor(hand)
            # 计算收获篮分配
            self._calculate_pots_for_hand(hand)
        else:
            # Post-flop: SB 先行动 (庄家后第一个活跃玩家)
            all_players = get_active_seated_players(self.db, hand.room_id)
            folded_ids = {
                b.player_id for b in self.db.query(Bet)
                .filter(Bet.hand_id == hand.id, Bet.action == "fold")
                .all()
            }
            # 可操作玩家: 非 fold 且 chip_count > 0
            actionable = [p for p in all_players if p.id not in folded_ids and p.chip_count > 0]

            if not actionable:
                # 所有人都 all-in 或 fold，直接跳到 showdown
                # 先继续发完公共牌
                while len(community) < 5:
                    deck.burn(1)
                    community.extend(deck.deal(1))
                hand.community_cards = cards_to_json(community)
                hand.deck_state = deck.to_json()
                hand.current_round = "showdown"
                hand.status = "settling"
                hand.turn_player_id = None
                self._compute_last_aggressor(hand)
                self._calculate_pots_for_hand(hand)
            else:
                seat_numbers = [p.seat_number for p in all_players]
                dealer = self.db.query(RoomPlayer).filter(RoomPlayer.id == hand.dealer_player_id).first()
                dealer_seat = dealer.seat_number if dealer else 0
                action_order = get_action_order(seat_numbers, dealer_seat, next_rnd)
                # 找第一个未 fold 且未 all-in 的玩家
                for seat in action_order:
                    p = self._find_player_by_seat(all_players, seat)
                    if p.id not in folded_ids and p.chip_count > 0:
                        hand.turn_player_id = p.id
                        break
                else:
                    hand.turn_player_id = None

        self.db.commit()
        self.db.refresh(hand)

        return hand

    def settle_hand(self, hand: Hand, results: list[dict] = None) -> list[HandResult]:
        """
        结算一季

        两种模式:
        1. 自动结算 (results=None): showdown 时自动评估牌力，或中途 fold 只剩一人
        2. 手动指定 (results=[{pot_id, winner_ids, amount}]): 岛主 override
        """
        if hand.status != "settling":
            raise BadRequestException("当前季节不在收获阶段")

        if results is None:
            results = self._auto_determine_winners(hand)

        hand_results = []
        for r in results:
            pot_id = r["pot_id"]
            winner_ids = r["winner_ids"]
            total_won = r.get("amount", 0)
            is_split = len(winner_ids) > 1
            share = total_won // len(winner_ids) if is_split else total_won

            for wid in winner_ids:
                hr = HandResult(
                    hand_id=hand.id,
                    pot_id=pot_id,
                    winner_id=wid,
                    amount_won=share,
                    is_split=1 if is_split else 0,
                )
                self.db.add(hr)
                hand_results.append(hr)

                # 给赢家加铃钱
                winner = self.db.query(RoomPlayer).filter(RoomPlayer.id == wid).first()
                if winner:
                    winner.chip_count += share

        hand.status = "settled"
        from datetime import datetime, timezone
        hand.settled_at = datetime.now(timezone.utc)

        self.db.commit()

        return hand_results

    def _auto_determine_winners(self, hand: Hand) -> list[dict]:
        """自动确定赢家（showdown 自动评估牌力，或中途 fold 只剩一人）"""
        pots = self.db.query(Pot).filter(Pot.hand_id == hand.id).all()
        all_bets = self.db.query(Bet).filter(Bet.hand_id == hand.id).all()
        folded_ids = {b.player_id for b in all_bets if b.action == "fold"}

        # 获取所有入座玩家
        seated_players = (
            self.db.query(RoomPlayer)
            .filter(RoomPlayer.room_id == self.room.id, RoomPlayer.is_active == 1, RoomPlayer.seat_number >= 0)
            .all()
        )
        alive_ids = [p.id for p in seated_players if p.id not in folded_ids]

        if not alive_ids:
            alive_ids = [seated_players[0].id] if seated_players else []

        community = cards_from_json(hand.community_cards) if hand.community_cards else []
        hole_cards_data = json.loads(hand.hole_cards) if hand.hole_cards else {}

        # 如果到达 showdown (5 张公共牌)，自动评估牌力
        if len(community) >= 5 and len(alive_ids) > 1:
            # 亮牌阶段: 仅比较选择亮牌的玩家
            revealed_ids = None
            if hand.revealed_players:
                revealed_ids = {int(x) for x in hand.revealed_players.split(",") if x}

            # 如果有亮牌数据，仅比较亮牌玩家
            if revealed_ids:
                compare_ids = [pid for pid in alive_ids if pid in revealed_ids]
            else:
                # 兜底: 没有亮牌数据 (例如 ended_by_fold 场景)，比较所有存活玩家
                compare_ids = alive_ids

            # 如果只有 1 个亮牌玩家，直接获胜
            if len(compare_ids) == 1:
                results = []
                for pot in pots:
                    eligible_str = pot.eligible_player_ids or ""
                    eligible = [int(x) for x in eligible_str.split(",") if x]
                    if compare_ids[0] in eligible:
                        winner_ids = compare_ids
                    else:
                        pot_alive = [pid for pid in compare_ids if pid in eligible]
                        winner_ids = pot_alive if pot_alive else compare_ids
                    results.append({
                        "pot_id": pot.id,
                        "winner_ids": winner_ids,
                        "amount": pot.amount,
                    })
                return results

            # 多个亮牌玩家: 比较牌力
            # 构建每个亮牌玩家的手牌
            player_scores = {}
            for pid in compare_ids:
                pid_str = str(pid)
                if pid_str in hole_cards_data:
                    hole = [Card.from_dict(c) for c in hole_cards_data[pid_str]]
                    if len(hole) >= 2:
                        score = evaluate_hand(hole, community)
                        player_scores[pid] = score

            if player_scores:
                results = []
                for pot in pots:
                    eligible_str = pot.eligible_player_ids or ""
                    eligible = [int(x) for x in eligible_str.split(",") if x]
                    pot_candidates = {pid: score for pid, score in player_scores.items() if pid in eligible}

                    if pot_candidates:
                        winner_ids = compare_hands(pot_candidates)
                    else:
                        winner_ids = compare_ids[:1]

                    results.append({
                        "pot_id": pot.id,
                        "winner_ids": winner_ids,
                        "amount": pot.amount,
                    })
                return results

        # 未到 showdown 或只有一个人: 最后一个存活者赢
        results = []
        for pot in pots:
            eligible_str = pot.eligible_player_ids or ""
            eligible = [int(x) for x in eligible_str.split(",") if x]
            pot_alive = [pid for pid in alive_ids if pid in eligible]
            if not pot_alive:
                pot_alive = alive_ids[:1]
            results.append({
                "pot_id": pot.id,
                "winner_ids": pot_alive,
                "amount": pot.amount,
            })
        return results

    def get_hand_evaluations(self, hand: Hand) -> dict:
        """获取所有存活玩家的牌力评估（用于前端展示）"""
        community = cards_from_json(hand.community_cards) if hand.community_cards else []
        hole_cards_data = json.loads(hand.hole_cards) if hand.hole_cards else {}

        all_bets = self.db.query(Bet).filter(Bet.hand_id == hand.id).all()
        folded_ids = {b.player_id for b in all_bets if b.action == "fold"}

        seated_players = (
            self.db.query(RoomPlayer)
            .filter(RoomPlayer.room_id == self.room.id, RoomPlayer.is_active == 1, RoomPlayer.seat_number >= 0)
            .all()
        )
        alive = [p for p in seated_players if p.id not in folded_ids]

        evaluations = {}
        if len(community) >= 3:
            for p in alive:
                pid_str = str(p.id)
                if pid_str in hole_cards_data:
                    hole = [Card.from_dict(c) for c in hole_cards_data[pid_str]]
                    if len(hole) >= 2:
                        score = evaluate_hand(hole, community)
                        evaluations[p.id] = {
                            "hand_type": score[0],
                            "hand_type_name": get_hand_type_name(score),
                        }
        return evaluations

    def rebuy(self, player: RoomPlayer, amount: int) -> Rebuy:
        """补给铃钱"""
        if amount <= 0:
            raise BadRequestException("补给金额必须大于0")

        player.chip_count += amount

        rebuy = Rebuy(
            room_player_id=player.id,
            amount=amount,
        )
        self.db.add(rebuy)
        self.db.commit()
        self.db.refresh(rebuy)

        return rebuy

    def _calculate_pots_for_hand(self, hand: Hand):
        """
        计算一季的所有收获篮 (主收获篮 + 副收获篮)

        德州扑克边池规则:
        1. 如果有玩家弃牌，存活玩家的有效投入上限 = 弃牌玩家中的最大投入
           超出部分退还给对应存活玩家
        2. 边池仅在 all-in 场景产生：某玩家筹码不够跟满，
           其投入金额以下的部分进入主池，以上部分进入边池
        """
        # 获取本季所有投入
        all_bets = self.db.query(Bet).filter(Bet.hand_id == hand.id).all()

        # 按玩家汇总
        player_totals = {}
        for b in all_bets:
            player_totals[b.player_id] = player_totals.get(b.player_id, 0) + b.amount

        # 已 fold 的玩家
        folded_ids = {
            b.player_id for b in all_bets if b.action == "fold"
        }

        # === Fold 退款：存活玩家的有效投入不超过 fold 者最大投入 ===
        # 例: A(BB=100) fold, B all-in 10000
        #   → B 的有效投入 cap 在 100, 退回 9900
        effective_bets = dict(player_totals)
        if folded_ids:
            max_folded_bet = max(
                (player_totals.get(pid, 0) for pid in folded_ids),
                default=0
            )
            for pid in list(effective_bets.keys()):
                if pid not in folded_ids and effective_bets[pid] > max_folded_bet:
                    refund = effective_bets[pid] - max_folded_bet
                    # 退回多余筹码
                    player = self.db.query(RoomPlayer).filter(
                        RoomPlayer.id == pid
                    ).first()
                    if player:
                        player.chip_count += refund
                    effective_bets[pid] = max_folded_bet
                    hand.pot_total -= refund

        # 用有效投入计算收获篮
        bets_list = [
            {"player_id": pid, "total_bet": total}
            for pid, total in effective_bets.items()
        ]

        pots_data = calculate_pots(bets_list)

        # 清除旧的收获篮记录
        self.db.query(Pot).filter(Pot.hand_id == hand.id).delete()

        for pd in pots_data:
            # 排除已 fold 的玩家 (他们不符合收获资格)
            eligible = [pid for pid in pd["eligible_player_ids"] if pid not in folded_ids]
            if not eligible:
                # 如果没人有资格，则分给最后没 fold 的人
                non_folded = [pid for pid in effective_bets if pid not in folded_ids]
                eligible = non_folded if non_folded else pd["eligible_player_ids"]

            pot = Pot(
                hand_id=hand.id,
                pot_type=pd["pot_type"],
                pot_level=pd["pot_level"],
                amount=pd["amount"],
                eligible_player_ids=",".join(str(pid) for pid in eligible),
            )
            self.db.add(pot)

        self.db.flush()

    def _find_player_by_seat(self, players: list[RoomPlayer], seat: int) -> RoomPlayer:
        for p in players:
            if p.seat_number == seat:
                return p
        raise BadRequestException(f"座位 {seat} 上没有玩家")
