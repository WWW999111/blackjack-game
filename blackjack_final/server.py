import socket
import random
import threading
import time
import queue
import sys
import os
import importlib.util

# 用绝对路径加载同目录模块（最可靠方式）
_DIR = os.path.dirname(os.path.abspath(__file__))

def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_DIR, name+".py"))
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

_items_mod    = _load("items")
_shop_mod     = _load("shop")
_gl_mod       = _load("game_logic")

EVENTS   = _items_mod.EVENTS
ITEMS    = _items_mod.ITEMS
Shop     = _shop_mod

get_deck          = _gl_mod.get_deck
calc              = _gl_mod.calc
is_blackjack      = _gl_mod.is_blackjack
is_ten            = _gl_mod.is_ten
is_ace            = _gl_mod.is_ace
can_split         = _gl_mod.can_split
is_split_aces     = _gl_mod.is_split_aces
dealer_should_hit = _gl_mod.dealer_should_hit
banker_must_hit   = _gl_mod.banker_must_hit
is_five_card_charlie = _gl_mod.is_five_card_charlie

players    = []   # 正式玩家（在大厅或等待中）
spectators = []   # 观战者（游戏进行中加入）
names      = {}
money      = {}
ready      = {}
msg_queues = {}
game_running = False   # 当前是否有游戏在进行

lock = threading.Lock()
WAIT_TIMEOUT = 60

# ===== 悬赏 / 排行榜 / 随机事件 全局变量 =====
win_streaks   = {}
loss_streaks  = {}
bounty_target = None
BOUNTY_STREAK = 3
BOUNTY_REWARD = 500

leaderboard = {
    "chips":      {},
    "win_streak": {},
    "loss_streak":{},
}

# 道具效果状态（每局重置）
_blinded_players     = set() # 被致盲的玩家
_gamble_multiplier   = {}   # {p: 3.5} 搏命契约
_soul_link           = {}   # {p: target_p} 灵魂链接绑定关系
_game_phase          = "idle"  # idle|betting|player_turn|dealer_turn|settle
# 阶段允许使用的主动道具
_PHASE_ALLOWED = {
    "betting":     {"搏命契约","灵魂链接"},
    "player_turn": {"透视眼镜","再来一次"},
    "other_turn":  {"强买强卖","致盲烟雾"},
    "any":         set(),  # 任何阶段（如移花接木在发牌后）
}
_forced_hit          = set() # 被强买强卖的玩家（下轮必须要牌）
_current_dealer_hand = []    # 当前局庄家完整手牌（供透视眼镜使用）
_paradox_pending     = set() # 时空悖论待触发的玩家（时光倒流后可用再来一次）
_paradox_blind_card  = {}    # {p: card} 时空悖论的盲抽暗牌
_reflect_shields     = set() # 拥有反弹镜像的玩家
_extra_draw          = set() # 再来一次已激活的玩家（可额外摸一张）

game_count    = 0
EVENT_INTERVAL= 3
current_event = "normal"

_prep_done_set   = set()   # 已完成prep准备的玩家连接集合
_current_hands   = {}      # 当前局各玩家手牌 {conn: [cards]}（供道具系统使用）
_current_deck    = []      # 当前局牌堆
_player_equipped = {}      # {conn: {"active":str,"passive":str}} 每局携带道具

# ===== 新道具/玩法全局状态（每局 game_loop 重置）=====
_doom_beacon        = False   # 厄运信标
_silence_field      = False   # 沉默干扰器
_duel_active        = False   # 决斗时代
_blood_moon_active  = False   # 血月之夜
_tornado_done       = False   # 龙卷风已执行
_vampire_mark       = {}      # 吸血印记 {target_p: caster_p}
_side_bets          = {}      # 外围下注 {bettor_p: {target,type,amount}}
_scale_tilt         = set()   # 天平倾斜（平局判赢）的玩家
_no_bet_players     = set()   # 本局禁止下注（通胀²惩罚）
_inflation_ban_next = set()   # 下局禁止下注（通胀²爆牌惩罚）

RELIEF_THRESHOLD = 100
RELIEF_AMOUNT    = 8888
RELIEF_MAX_DAILY = 3
relief_records   = {}

def send(p, msg):
    try:   p.send((msg + "\n").encode())
    except: remove_player(p)

def broadcast(msg):
    """广播给所有正式玩家"""
    for p in players[:]:
        send(p, msg)

def broadcast_spectators(msg):
    """广播给所有观战者"""
    for p in spectators[:]:
        send(p, msg)

def broadcast_all(msg):
    """广播给所有人（含观战者）"""
    broadcast(msg)
    broadcast_spectators(msg)

def broadcast_lobby_status():
    with lock:
        total       = len(players)
        ready_count = sum(1 for p in players if ready.get(p, False))
        spec_count  = len(spectators)
    broadcast(f"[LOBBY]{total}|{ready_count}")
    # 告诉观战者当前观战人数和游戏状态
    for p in spectators[:]:
        send(p, f"[SPECTATE]{spec_count}|{total}")

def remove_player(p):
    with lock:
        removed = False
        if p in players:
            print(f"{names.get(p,'玩家')} 断开连接")
            players.remove(p)
            removed = True
        elif p in spectators:
            print(f"{names.get(p,'观战者')} 断开连接")
            spectators.remove(p)
            removed = True
        if removed:
            names.pop(p, None)
            money.pop(p, None)
            ready.pop(p, None)
            msg_queues.pop(p, None)
            try: p.close()
            except: pass
    if p in players or True:  # 总是广播更新
        broadcast_lobby_status()

def recv_from_queue(p, timeout=30):
    q = msg_queues.get(p)
    if q is None: return None
    try:    return q.get(timeout=timeout)
    except queue.Empty: return None

def player_recv_thread(conn):
    buffer = ""
    while True:
        try:
            conn.settimeout(None)
            data = conn.recv(2048).decode()
            if not data:
                remove_player(conn); break
            buffer += data
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line: continue
                # 道具使用在收到时立即处理，不进队列
                if line.startswith("[USE_ITEM]"):
                    _handle_use_item(conn, line)
                    continue
                # 协议前缀剥离，服务器内部只处理纯内容
                if line.startswith("[ACTION]"):
                    line = line[len("[ACTION]"):]
                elif line.startswith("[BET]"):
                    line = line[len("[BET]"):]
                elif line.startswith("[GRAB]"):
                    line = line[len("[GRAB]"):]
                elif line.startswith("[INSURANCE]"):
                    line = line[len("[INSURANCE]"):]
                elif line.startswith("[SYNC_MONEY]"):
                    try:
                        money[conn] = max(0, int(line.replace("[SYNC_MONEY]","").strip()))
                    except:
                        pass
                    continue
                elif line.startswith("[SYNC_BOX_EFFECT]"):
                    try:
                        _payload = line.replace("[SYNC_BOX_EFFECT]","").strip()
                        _parts = _payload.split("|")
                        _kind = _parts[0].strip()
                        _gid  = int(_parts[1].strip()) if len(_parts) > 1 else game_count
                        _pname2 = names.get(conn,"?")
                        if _kind == "superjackpot":
                            getattr(Shop, "set_lucky_buff", lambda a,b,c=3: None)(_pname2, _gid, 3)
                        elif _kind == "forced_hit":
                            getattr(Shop, "set_forced_opening_hit", lambda a,b: None)(_pname2, _gid)
                    except:
                        pass
                    continue
                elif line == "[PREP_DONE]":
                    _prep_done_set.add(conn)
                    continue
                elif line.startswith("[EQUIPPED]"):
                    _parts_eq = line.replace("[EQUIPPED]","").split("|")
                    _eq_active  = _parts_eq[0].strip() if len(_parts_eq)>0 else ""
                    _eq_passive = _parts_eq[1].strip() if len(_parts_eq)>1 else ""
                    _player_equipped[conn] = {"active": _eq_active, "passive": _eq_passive}
                    continue
                q = msg_queues.get(conn)
                if q: q.put(line)
        except Exception as _e:
            print(f"[接收线程] 玩家 {names.get(conn,'?')} 断开: {_e}")
            remove_player(conn); break

def _phase_allowed(iname, p, current_players):
    """检查当前阶段是否允许使用该道具"""
    # 被动道具不需要手动触发
    from items import PASSIVE_ITEMS
    if iname in PASSIVE_ITEMS:
        return False, "被动道具自动触发，无需手动使用"
    # 阶段限制
    phase = _game_phase
    rules = {
        "搏命契约": ["betting"],
        "灵魂链接": ["betting"],
        "透视眼镜": ["player_turn"],
        "再来一次": ["player_turn"],
        "强买强卖": ["other_turn","player_turn"],
        "致盲烟雾": ["other_turn","player_turn"],
        "移花接木": ["player_turn"],
    }
    allowed = rules.get(iname, ["player_turn","other_turn","betting"])
    if phase not in allowed:
        phase_names = {"idle":"准备阶段","betting":"下注阶段",
                       "player_turn":"你的回合","other_turn":"他人回合",
                       "dealer_turn":"庄家回合","settle":"结算阶段"}
        return False, f"当前{phase_names.get(phase,'阶段')}不能使用【{iname}】"
    return True, ""

def _handle_use_item(p, raw, is_reflected=False):
    """立即处理道具使用，含阶段检查和优先级"""
    _raw_parts = raw.replace("[USE_ITEM]","").strip().split("|",1)
    iname   = _raw_parts[0].strip()
    _target_name = _raw_parts[1].strip() if len(_raw_parts)>1 else ""
    target_p = None
    if _target_name:
        for _cp in list(players):
            if names.get(_cp,"") == _target_name:
                target_p = _cp; break
    pname = names.get(p,"?")
    print(f"[道具] {pname} 使用 {iname} -> {_target_name or '无目标'} (phase={_game_phase})")

    # 检查是否携带此道具（prep阶段选择的）
    equipped = _player_equipped.get(p, {})
    from items import PASSIVE_ITEMS as _PI_chk
    if iname in _PI_chk:
        if equipped and equipped.get("passive","") != iname:
            send(p, f"[INFO]⚠ 【{iname}】未携带，无法触发")
            return
    else:
        if equipped and equipped.get("active","") != iname and iname != "命运盲盒":
            send(p, f"[INFO]⚠ 【{iname}】未携带，无法使用")
            return

    # 阶段检查
    ok, reason = _phase_allowed(iname, p, list(players))
    if not ok:
        send(p, f"[INFO]❌ 无法使用【{iname}】：{reason}")
        return

    if iname == "透视眼镜":
        if _current_dealer_hand:
            send(p, f"[DEALER_REVEAL]{_current_dealer_hand}")
            send(p, f"[INFO]👁 透视眼镜：庄家暗牌是 {_current_dealer_hand[0]}")
        else:
            send(p, "[INFO]👁 透视眼镜：牌局未开始")
        broadcast_all(f"[INFO]👁 {pname} 使用了透视眼镜！")

    elif iname == "再来一次":
        if p in _paradox_pending:
            _paradox_pending.discard(p)
            _extra_draw.add(p)
            send(p, "[PARADOX]")
            broadcast_all(f"[INFO]⚡ 【时空悖论】{pname} 触发！盲抽一张命运之牌...")
        else:
            _extra_draw.add(p)
            send(p, "[INFO]🎲 再来一次激活！将额外获得一次摸牌机会")
            broadcast_all(f"[INFO]🎲 {pname} 使用了再来一次！")

    elif iname == "强买强卖":
        with lock:
            targets = [op for op in players if op != p]
        if targets:
            target_p = random.choice(targets)
            if target_p in _reflect_shields:
                _reflect_shields.discard(target_p)
                _forced_hit.add(p)
                tname = names.get(target_p,"?")
                send(target_p, f"[INFO]🛡 反弹镜像！强买强卖被弹回给 {pname}！")
                send(p, f"[INFO]🛡 你的强买强卖被 {tname} 的反弹镜像挡回来了！")
                broadcast_all(f"[INFO]🛡 {tname} 反弹了 {pname} 的强买强卖！")
            else:
                _forced_hit.add(target_p)
                tname = names.get(target_p,"?")
                send(p, f"[INFO]🃏 强买强卖！{tname} 下次必须要牌")
                send(target_p, "[INFO]🃏 被强买强卖！下次轮到你时强制要牌")
                broadcast_all(f"[INFO]🃏 {pname} 对 {tname} 使用了强买强卖！")

    elif iname == "致盲烟雾":
        with lock:
            targets = [op for op in players if op != p]
        if targets:
            target_p = random.choice(targets)
            if target_p in _reflect_shields:
                _reflect_shields.discard(target_p)
                _blinded_players.add(p)
                tname = names.get(target_p,"?")
                send(target_p, f"[INFO]🛡 反弹镜像！致盲烟雾被弹回给 {pname}！")
                send(p, "[BLINDED]")
                broadcast_all(f"[INFO]🛡 {tname} 反弹了 {pname} 的致盲烟雾！")
            else:
                _blinded_players.add(target_p)
                tname = names.get(target_p,"?")
                send(target_p, "[BLINDED]")
                send(p, f"[INFO]🌫 致盲了 {tname}！")
                broadcast_all(f"[INFO]🌫 {pname} 对 {tname} 使用了致盲烟雾！")

    elif iname == "搏命契约":
        _gamble_multiplier[p] = 3.5
        send(p, "[INFO]💣 搏命契约激活！本局胜负筹码×3.5")
        broadcast_all(f"[INFO]💣 {pname} 立下搏命契约！")

    elif iname == "移花接木":
        send(p, "[INFO]🔀 移花接木已激活，本局初始发牌后可与任意玩家互换一张明牌")
        broadcast_all(f"[INFO]🔀 {pname} 使用了移花接木！")

    elif iname == "灵魂链接":
        # 找筹码最多的玩家
        richest = None; max_chips = -1
        for op in players:
            if op != p and money.get(op,0) > max_chips:
                max_chips = money.get(op,0); richest = op
        if richest is None:
            send(p, "[INFO]🔗 灵魂链接：场上没有其他玩家可绑定")
            return
        rname = names.get(richest,"?")
        # 套娃检测：目标已经绑定了别人
        if richest in _soul_link or any(v==p for v in _soul_link.values()):
            send(p, "[INFO]🔗 灵魂链接：目标灵魂过于混乱，绑定失败！")
            return
        _soul_link[p] = richest
        send(p, f"[INFO]🔗 已绑定 {rname}！他赢你分钱，他爆你跟爆")
        send(richest, f"[INFO]🔗 {pname} 对你使用了灵魂链接！")
        broadcast_all(f"[INFO]🔗 {pname} 灵魂绑定了 {rname}！")

    elif iname == "回炉重造":
        _ph = _current_hands.get(p, [])
        if len(_ph) == 2:
            old_cards = _ph[:]
            _current_deck.extend(old_cards); random.shuffle(_current_deck)
            new_cards = [_current_deck.pop(), _current_deck.pop()]
            _current_hands[p] = new_cards
            val = calc(new_cards)
            send(p, f"[HAND]{new_cards}|{val}")
            send(p, f"[INFO]♻️ 回炉重造！扔掉{old_cards}，新牌:{new_cards}({val}点)")
            broadcast_all(f"[INFO]♻️ {pname} 使用了回炉重造！")
        else:
            send(p, "[INFO]♻️ 回炉重造只能在初始两张牌时使用！")

    elif iname == "狸猫换太子":
        if hands.get(p) and _current_dealer_hand:
            p_card = min(hands[p], key=lambda c: calc([c]))
            d_idx  = 1 if len(_current_dealer_hand)>1 else 0
            d_card = _current_dealer_hand[d_idx]
            hands[p].remove(p_card); hands[p].append(d_card)
            _current_dealer_hand[d_idx] = p_card
            val = calc(hands[p])
            send(p, f"[HAND]{hands[p]}|{val}")
            send(p, f"[INFO]🎭 狸猫换太子！你的{p_card}换了庄家的{d_card}")
            broadcast_all(f"[INFO]🎭 {pname} 与庄家互换了一张牌！")
        else:
            send(p, "[INFO]🎭 无法互换：你或庄家没有合适的手牌")

    elif iname == "厄运信标":
        _doom_beacon = True
        broadcast_all(f"[INFO]🧨 {pname} 埋下了厄运信标！下一个要牌的人必抽10点牌！")

    elif iname == "第三只手":
        targets = [op for op in players if op != p]
        if targets:
            target = random.choice(targets)
            tname  = names.get(target,"?")
            try:
                t_pd = Shop.get_player_data(tname)
                t_items = t_pd.get("items",{})
                if t_items:
                    stolen = random.choice(list(t_items.keys()))
                    Shop.use_item(tname, stolen)
                    my_pd = Shop.get_player_data(pname)
                    my_items2 = my_pd.get("items",{})
                    my_items2[stolen] = my_items2.get(stolen,0)+1
                    Shop.save_player_data(pname, {"items":my_items2})
                    send(p,      f"[INFO]🧤 偷到了{tname}的【{stolen}】！")
                    send(target, f"[INFO]🧤 你的【{stolen}】被{pname}偷走了！")
                else:
                    stolen_chips = min(200, money.get(target,0))
                    money[target] = money.get(target,0) - stolen_chips
                    money[p]      = money.get(p,0)      + stolen_chips
                    send(p,      f"[INFO]🧤 {tname}没有道具，偷走了{stolen_chips}筹码！")
                    send(target, f"[INFO]🧤 {pname}偷走了你{stolen_chips}筹码！")
            except Exception as e:
                send(p, f"[INFO]🧤 第三只手：{e}")
        else:
            send(p, "[INFO]🧤 场上没有其他玩家可偷")

    elif iname == "吸血印记":
        targets = [op for op in players if op != p]
        if targets:
            target = random.choice(targets)
            _vampire_mark[target] = p
            send(p,      f"[INFO]🧛 吸血印记已附在{names.get(target,'?')}身上！他赢了分你20%")
            send(target, f"[INFO]🧛 {pname}对你施加了吸血印记！赢了要分20%利润！")
        else:
            send(p, "[INFO]🧛 没有目标可以寄生")

    elif iname == "沉默干扰器":
        _silence_field = True
        broadcast_all(f"[INFO]🤫 {pname} 开启沉默干扰！本局所有主动道具无法使用！")

    elif iname == "命运盲盒":
        import shop as _shop_box
        result = getattr(_shop_box, "_open_blind_box", lambda a,b: "nothing:无效")(pname, game_count)
        send(p, f"[BLINDBOX_RESULT]{result}")
        send(p, f"[INFO]📦 {pname} 开启命运盲盒...")
        if "curse:leak" in result:
            penalty = max(100, int(money.get(p,0) * 0.10))
            money[p] = max(0, money.get(p,0) - penalty)
            send(p, f"[INFO]💀 漏财！扣除 {penalty} 筹码")
        elif "curse:blind" in result:
            _blinded_players.add(p)
            send(p, "[BLINDED]")
            send(p, "[INFO]💀 小丑的戏法！你看不见自己的牌了！")
        elif "curse:forced_hit" in result:
            _target_gid = game_count if _game_phase in ("idle","betting") else (game_count + 1)
            getattr(_shop_box, "set_forced_opening_hit", lambda a,b: None)(pname, _target_gid)
            send(p, f"[INFO]💀 上头了！将在第{_target_gid}局开局自动多摸一张牌！")
        elif "superjackpot" in result:
            _target_gid = game_count if _game_phase in ("idle","betting") else (game_count + 1)
            getattr(_shop_box, "set_lucky_buff", lambda a,b,c=3: None)(pname, _target_gid, 3)
            send(p, f"[INFO]⭐ 特等奖！从第{_target_gid}局起连续3局，你每局都有88.8%概率直接黑杰克！")


def check_relief(p):
    import datetime
    name  = names.get(p, '')
    today = datetime.date.today().isoformat()
    rec   = relief_records.get(name, {"date": "", "count": 0})
    if rec["date"] != today:
        rec = {"date": today, "count": 0}
    if money.get(p, 0) < RELIEF_THRESHOLD and rec["count"] < RELIEF_MAX_DAILY:
        rec["count"] += 1
        relief_records[name] = rec
        money[p] = money.get(p, 0) + RELIEF_AMOUNT
        return RELIEF_AMOUNT
    return 0

# ===== 单手牌回合 =====
def play_hand(p, hand, deck, current_players, bet,
              allow_double=True, allow_split=True,
              allow_surrender=True, is_after_split_aces=False,
              force_hit_below=-1, depth=0):
    pname = names.get(p, '?')

    global _game_phase, _doom_beacon, _silence_field, _reflect_shields
    global _blinded_players, _gamble_multiplier, _paradox_pending, _paradox_blind_card
    global _extra_draw, _forced_hit, _current_dealer_hand
    global _vampire_mark, _scale_tilt, _blood_moon_active

    # 检查玩家是否还在线
    print(f"[服务器] play_hand 开始: {pname}, hand={hand}")
    import sys; sys.stdout.flush()
    with lock:
        if p not in players and p not in spectators:
            print(f"[服务器] {pname} 已断线，跳过")
            return [hand], [bet], False  # 玩家已断线，跳过
    _game_phase = "player_turn"
    broadcast_all(f"[INFO]轮到 {pname} 操作")
    for other in current_players:
        if other != p:
            send(other, f"[WAITING_FOR]{pname}")
            # 其他玩家此时处于 other_turn 阶段
    # 通知所有其他人当前阶段
    for other in current_players:
        if other != p:
            msg_queues.get(other)  # 不需要发消息，_game_phase已全局更新
    # 观战者也看到等待提示
    broadcast_spectators(f"[WAITING_FOR]{pname}")
    send(p, "[WAITING_FOR]")
    send(p, f"[HAND]{hand}|{calc(hand)}")

    if is_after_split_aces:
        card = deck.pop()
        hand.append(card)
        val = calc(hand)
        send(p, f"[HAND]{hand}|{val}")
        send(p, f"[INFO]分A只能再要一张: {card}，点数: {val}")
        return [hand], [bet], [False]

    # 强制要牌阶段
    while force_hit_below >= 0 and calc(hand) <= force_hit_below:
        card = deck.pop()
        hand.append(card)
        val = calc(hand)
        send(p, f"[HAND]{hand}|{val}")
        send(p, f"[INFO]点数不足{force_hit_below+1}，强制要牌: {card}，点数: {val}")
        for other in current_players:
            if other != p:
                send(other, f"[INFO]{pname} 强制摸牌")
        broadcast_spectators(f"[INFO]{pname} 强制摸牌: {card}，点数: {val}")
        if val > 21:
            send(p, "[INFO]💥 强制要牌后爆牌！")
            broadcast_all(f"[INFO]💥 {pname} 爆牌了！")
            return [hand], [bet], [False]

    def send_options():
        opts = ["HIT", "STAND"]
        if allow_double and len(hand) == 2 and money.get(p, 0) >= bet:
            opts.append("DOUBLE")
        if allow_split and can_split(hand) and len(hand) == 2 and money.get(p, 0) >= bet:
            opts.append("SPLIT")
        if allow_surrender and len(hand) == 2 and depth == 0:
            opts.append("SURRENDER")
        send(p, f"[OPTIONS]{','.join(opts)}")
        print(f"[服务器] 发送OPTIONS给 {pname}: {opts}")
        import sys; sys.stdout.flush()

    # 强买强卖：如果被标记，第一次操作必须要牌
    if p in _forced_hit:
        _forced_hit.discard(p)
        send(p, "[INFO]🃏 被强买强卖！强制要牌一次")
        card = deck.pop()
        hand.append(card)
        val = calc(hand)
        send(p, f"[HAND]{hand}|{val}")
        if val > 21:
            send(p, "[INFO]💥 强制要牌后爆牌！")
            broadcast_all(f"[INFO]💥 {pname} 被强买强卖后爆牌！")
            return [hand], [bet], [False]
        send_options()
    else:
        send_options()

    while True:
        if is_five_card_charlie(hand):
            send(p, "[INFO]🐉 五龙！5张牌未爆，直接胜！")
            broadcast_all(f"[INFO]🐉 {pname} 五龙！")
            return [hand], [bet], [False]

        # 阻塞等待消息，收到后判断类型
        raw = recv_from_queue(p, timeout=60)
        if raw is None: raw = "STAND"

        # [USE_ITEM] 已在 player_recv_thread 里处理，这里不会收到
        choice = raw


        if choice == "HIT":
            # 厄运信标：强制抽10点牌
            if _doom_beacon:
                tens = [c for c in deck if calc([c]) == 10]
                card = random.choice(tens) if tens else deck.pop()
                if tens: deck.remove(card)
                _doom_beacon = False
                send(p, "[INFO]🧨 厄运信标触发！强制抽到10点牌！")
                broadcast_all(f"[INFO]🧨 信标爆炸！{names.get(p,'?')}抽到10点！")
            else:
                card = deck.pop()
            hand.append(card)
            val  = calc(hand)
            send(p, f"[HAND]{hand}|{val}")
            send(p, f"[INFO]你摸了 {card}，当前点数: {val}")
            for other in current_players:
                if other != p:
                    send(other, f"[INFO]{pname} 要了一张牌")
            broadcast_spectators(f"[INFO]{pname} 要牌: {card}，点数: {val}")
            if val > 21:
                # 检查时光倒流（被动）
                import shop as _shop_mod
                _pname_key = names.get(p,"?")
                _pd = _shop_mod.get_player_data(_pname_key)
                if _pd.get("items",{}).get("时光倒流",0) > 0:
                    hand.pop(); deck.insert(0, card)
                    _items2 = _pd["items"]
                    _items2["时光倒流"] -= 1
                    if _items2["时光倒流"] <= 0: del _items2["时光倒流"]
                    _shop_mod.save_player_data(_pname_key, {"items":_items2})
                    send(p, f"[HAND]{hand}|{calc(hand)}")
                    send(p, "[INFO]⏳ 时光倒流触发！退回了爆牌的牌")
                    broadcast_all(f"[INFO]⏳ {pname} 时光倒流触发！")
                    send(p, "[ITEM_USED]时光倒流")
                    # 检查玩家是否有"再来一次"，若有则进入时空悖论等待
                    _pd2 = _shop_mod.get_player_data(_pname_key)
                    if _pd2.get("items",{}).get("再来一次",0) > 0:
                        _paradox_pending.add(p)
                        send(p, "[INFO]⚡ 你有「再来一次」！使用它可触发【时空悖论】Combo！")
                        send(p, "[PARADOX_READY]")  # 提示客户端可触发
                        # 等10秒让玩家决定是否触发paradox
                        raw2 = recv_from_queue(p, timeout=10)
                        if raw2 and raw2.startswith("[USE_ITEM]再来一次"):
                            _handle_use_item(p, raw2)
                    if p in _paradox_pending:
                        _paradox_pending.discard(p)
                    # 强制停牌（时光倒流后）
                    return [hand], [bet], [False]
                send(p, "[INFO]💥 你爆牌了！")
                broadcast_all(f"[INFO]💥 {pname} 爆牌了！")
                return [hand], [bet], [False]
            if is_five_card_charlie(hand):
                send(p, "[INFO]🐉 五龙！5张牌未爆，直接胜！")
                broadcast_all(f"[INFO]🐉 {pname} 五龙！")
                return [hand], [bet], [False]
            send(p, "[OPTIONS]HIT,STAND")

        elif choice == "STAND":
            # 检查 再来一次（普通使用，非paradox）
            if p in _extra_draw and p not in _paradox_blind_card:
                _extra_draw.discard(p)
                card2 = deck.pop()
                hand.append(card2)
                val2 = calc(hand)
                send(p, f"[HAND]{hand}|{val2}")
                send(p, f"[INFO]🎲 再来一次！额外摸了 {card2}，点数: {val2}")
                broadcast_all(f"[INFO]🎲 {pname} 再来一次，摸了一张牌！")
                if val2 > 21:
                    send(p, "[INFO]💥 额外摸牌后爆牌！")
                    broadcast_all(f"[INFO]💥 {pname} 再来一次后爆牌！")
                else:
                    send(p, f"[INFO]停牌，最终点数: {val2}")
                return [hand], [bet], [False]
            send(p, f"[INFO]你停牌，点数: {calc(hand)}")
            broadcast_all(f"[INFO]{pname} 停牌，点数: {calc(hand)}")
            return [hand], [bet], [False]

        elif choice == "DOUBLE" and allow_double and len(hand) == 2 and money.get(p, 0) >= bet:
            money[p] = money.get(p, 0) - bet
            new_bet  = bet * 2
            card = deck.pop()
            hand.append(card)
            val  = calc(hand)
            send(p, f"[HAND]{hand}|{val}")
            send(p, f"[INFO]加倍！摸了 {card}，点数: {val}，本手赌注: {new_bet}")
            broadcast_all(f"[INFO]{pname} 加倍！点数: {val}")
            if val > 21:
                send(p, "[INFO]💥 加倍后爆牌！")
                broadcast_all(f"[INFO]💥 {pname} 加倍后爆牌！")
            return [hand], [new_bet], [False]

        elif choice == "SPLIT" and allow_split and can_split(hand) and len(hand) == 2 and money.get(p, 0) >= bet:
            money[p] = money.get(p, 0) - bet
            splitting_aces = is_split_aces(hand)
            hand1 = [hand[0], deck.pop()]
            hand2 = [hand[1], deck.pop()]
            send(p, f"[INFO]分牌！手牌1: {hand1}  手牌2: {hand2}")
            broadcast_all(f"[INFO]{pname} 分牌了！")
            h1, b1, bj1 = play_hand(p, hand1, deck, current_players, bet,
                                     allow_double=not splitting_aces,
                                     allow_split=False, allow_surrender=False,
                                     is_after_split_aces=splitting_aces, depth=depth+1)
            h2, b2, bj2 = play_hand(p, hand2, deck, current_players, bet,
                                     allow_double=not splitting_aces,
                                     allow_split=False, allow_surrender=False,
                                     is_after_split_aces=splitting_aces, depth=depth+1)
            return h1+h2, b1+b2, bj1+bj2

        elif choice == "SURRENDER" and allow_surrender and len(hand) == 2 and depth == 0:
            refund = bet // 2
            money[p] = money.get(p, 0) + refund
            send(p, f"[INFO]投降，返还 {refund} 筹码")
            broadcast_all(f"[INFO]{pname} 投降了")
            return [], [], []

        else:
            send_options()

# ===== 游戏主循环 =====

def apply_event_to_calc(hand, event):
    """计算点数和是否爆牌，含随机事件规则"""
    val = calc(hand)
    if event == "speed":
        return val, val > 17
    if event == "bloodmoon":
        has_spade = any(c.startswith("♠") for c in hand)
        return val, has_spade
    return val, val > 21

def dealer_should_hit_event(hand, event):
    """庄家补牌判断，含极速局规则"""
    val = calc(hand)
    if event == "speed":
        if val > 17: return False
        return val < 13
    return dealer_should_hit(hand)

def is_blackjack_event(hand, event):
    """BJ判断，极速局下A+6=17也算BJ"""
    if event == "speed":
        if len(hand) != 2: return False
        return calc(hand) == 17 and any(is_ace(c) for c in hand)
    return is_blackjack(hand)

def game_loop():
    global game_running, _game_phase, game_count, current_event, _prep_done_set, _player_equipped
    global _current_hands, _current_deck
    global _current_dealer_hand, _doom_beacon, _silence_field
    global _duel_active, _blood_moon_active, _tornado_done
    global _vampire_mark, _side_bets, _scale_tilt, _no_bet_players, _inflation_ban_next
    global bounty_target, win_streaks, loss_streaks, leaderboard
    while True:
        while len(players) < 1:
            time.sleep(0.5)

        game_running = False

        with lock:
            for p in players:
                ready[p] = False

        broadcast("[WAITING]")
        broadcast_lobby_status()

        # ===== 准备阶段 =====
        start_time = time.time()
        while True:
            time.sleep(0.5)
            with lock:
                current = list(players)
            for p in current:
                q = msg_queues.get(p)
                if q is None: continue
                pending = []
                while True:
                    try:
                        line = q.get_nowait()
                        if line == "[READY]":
                            with lock: ready[p] = True
                            broadcast_all(f"[INFO]✅ {names.get(p,'?')} 已准备")
                            broadcast_lobby_status()
                        elif line == "[UNREADY]":
                            with lock: ready[p] = False
                            broadcast_lobby_status()
                        elif line.startswith("[SIDE_BET]"):
                            # 外围下注格式: [SIDE_BET]目标名|类型(bust/win)|金额
                            try:
                                parts = line.replace("[SIDE_BET]","").split("|")
                                tname2 = parts[0]; btype = parts[1]; bamt = int(parts[2])
                                target2 = next((op for op in players if names.get(op)==tname2), None)
                                pname2  = names.get(p,"?")
                                if target2 and target2 != p and money.get(p,0)>=bamt and bamt>0:
                                    money[p] -= bamt
                                    _side_bets[p] = {"target":target2,"type":btype,"amount":bamt}
                                    btype_cn = "爆牌" if btype=="bust" else "赢庄家"
                                    send(p, f"[INFO]🎲 外围下注：押{tname2}会{btype_cn}，金额{bamt}")
                                    broadcast_all(f"[INFO]🎲 {pname2}押{tname2}会{btype_cn}！{bamt}筹码！")
                                else:
                                    send(p, "[INFO]🎲 外围下注失败（筹码不足或目标无效）")
                            except: pass
                        elif line == "[RELIEF]":
                            gained = check_relief(p)
                            if gained > 0:
                                send(p, f"[RELIEF_OK]{money[p]}")
                                send(p, f"[INFO]💰 领取救济金 {gained}，当前: {money[p]}")
                            else:
                                send(p, "[RELIEF_FAIL]")
                        else:
                            pending.append(line)
                    except queue.Empty: break
                for line in pending: q.put(line)

            with lock:
                current     = [p for p in players if p in money]
                if not current: break
                all_ready   = all(ready.get(p, False) for p in current)
                elapsed     = time.time() - start_time
                ready_count = sum(1 for p in current if ready.get(p, False))

            broadcast(f"[LOBBY]{len(current)}|{ready_count}|0")
            if all_ready and len(current) >= 2: break

        with lock:
            current_players = [p for p in players if p in money]
        if not current_players: continue

        game_running = True
        # (globals declared at function top)
        try:
            _current_dealer_hand = []
            _blinded_players.clear()
            _forced_hit.clear()
            _gamble_multiplier.clear()
            _soul_link.clear()
            _game_phase = "idle"
            _paradox_pending.clear()
            _paradox_blind_card.clear()
            _reflect_shields.clear()
            _extra_draw.clear()
            _vampire_mark.clear()
            _side_bets.clear()
            _scale_tilt.clear()
            _doom_beacon = False; _silence_field = False
            _duel_active = False; _blood_moon_active = False; _tornado_done = False
    
            # ===== 抢庄阶段 =====
            broadcast("[GRABBING]")
            broadcast_spectators("[INFO]游戏即将开始（抢庄阶段）")
            grab_results = {}
    
            def collect_grab(p):
                val = recv_from_queue(p, timeout=30)
                grab_results[p] = (val == "1")   # 客户端发 [GRAB]1 或 [GRAB]0
    
            gt = [threading.Thread(target=collect_grab, args=(p,)) for p in current_players]
            for t in gt: t.start()
            for t in gt: t.join()
    
            grabbers = [p for p in current_players if grab_results.get(p, False)]
            banker   = random.choice(grabbers) if grabbers else None
    
            if banker:
                bname = names.get(banker, '?')
                broadcast(f"[BANKER]{bname}")
                broadcast_spectators(f"[BANKER]{bname}")
            else:
                broadcast("[BANKER]系统")
                broadcast_spectators("[BANKER]系统")
    
            time.sleep(1.5)
            # 选取随机事件
            ev_key = pick_event()
            # 检查哪些玩家有反弹镜像，加入 _reflect_shields
            import shop as _shop_start
            for _pp in current_players:
                _ppn = names.get(_pp,"?")
                _ppd = _shop_start.get_player_data(_ppn)
                if _ppd.get("items",{}).get("反弹镜像",0) > 0:
                    _reflect_shields.add(_pp)
            game_count += 1
            print(f"[服务器] 发送 GAMESTART {game_count}, 事件={ev_key}")
            broadcast(f"[GAMESTART]{game_count}")
            broadcast(f"[EVENT]{ev_key}")
            broadcast_spectators("[SPECTATING]")
            broadcast_spectators(f"[EVENT]{ev_key}")
            if ev_key != "normal":
                from items import EVENTS
                ev = EVENTS.get(ev_key,{})
                broadcast_all(f"[INFO]🌪 特殊规则: {ev.get('name','')} - {ev.get('desc','')}")
    
            deck = get_deck()
            random.shuffle(deck)

            dealer_is_human = banker is not None
            non_bankers     = [p for p in current_players if p != banker] if banker else current_players

            # ===== 等待玩家道具准备（固定60秒）=====
            _prep_done_set.clear()
            _player_equipped.clear()
            _prep_done_set.clear()
            broadcast("[PREP_START]")
            # 等所有玩家确认，最多60秒
            _pt = 0
            while _pt < 600:
                if all(p in _prep_done_set for p in current_players):
                    break
                time.sleep(0.1); _pt += 1

            # ===== 下注（并行，发牌前完成）=====
            _game_phase = "betting"
            bet_results = {}
            print(f"[服务器] 下注阶段: non_bankers={[names.get(p,'?') for p in non_bankers]}, banker={names.get(banker,'系统')}")
            for p in non_bankers:
                if money.get(p, 0) <= 0:
                    send(p, "[INFO]筹码不足，本局跳过下注")
                else:
                    send(p, f"[BET]{money[p]}")
                    print(f"[服务器] 发送 BET 给 {names.get(p,'?')}: {money[p]}")
            if dealer_is_human:
                send(banker, "[INFO]你是庄家，等待闲家下注...")
            broadcast_spectators("[INFO]下注阶段...")
    
            def collect_bet(p):
                cur = money.get(p, 0)
                if cur <= 0:
                    bet_results[p] = 0; return
                # 等待玩家下注，最多60秒
                bet_data = recv_from_queue(p, timeout=60)
                print(f"[服务器] collect_bet {names.get(p,'?')} 收到: {repr(bet_data)}")
                try:    bet = int(bet_data)
                except: bet = min(100, cur)
                bet_results[p] = max(1, min(bet, cur))
    
            bt = [threading.Thread(target=collect_bet, args=(p,)) for p in non_bankers]
            for t in bt: t.start()
            print(f"[服务器] 等待所有人下注...")
            import sys; sys.stdout.flush()
            for t in bt: t.join()
            print(f"[服务器] 所有人下注完成: {bet_results}")
            sys.stdout.flush()
    
            bets = {}
            for p in non_bankers:
                bet = bet_results.get(p, 0)
                money[p] = money.get(p, 0) - bet
                bets[p]  = bet
                broadcast_spectators(f"[INFO]{names.get(p,'?')} 下注 {bet}")
    
            # ===== 下注完成后才发牌 =====
            print(f"[服务器] 下注完成，准备发牌给 {[names.get(p,'?') for p in current_players]}")
            import sys; sys.stdout.flush()
            hands = {}
            for p in current_players:
                pname_cur = names.get(p, "?")
                lucky_hand = None
                try:
                    if getattr(Shop, "consume_lucky_buff", lambda a,b: False)(pname_cur, game_count):
                        import random as _rnd
                        if _rnd.random() < 0.888:
                            lucky_hand = _draw_weighted_blackjack(deck)
                            if lucky_hand:
                                send(p, "[INFO]⭐ 特等奖生效！本局你几乎天胡！")
                except:
                    lucky_hand = None
                hands[p] = lucky_hand if lucky_hand else [deck.pop(), deck.pop()]
                try:
                    if getattr(Shop, "consume_forced_opening_hit", lambda a,b: False)(pname_cur, game_count):
                        if deck:
                            _extra_c = deck.pop()
                            hands[p].append(_extra_c)
                            send(p, f"[INFO]💀 上头了生效！开局自动摸牌: {_extra_c}")
                except:
                    pass
            dealer_hand = hands[banker] if dealer_is_human else [deck.pop(), deck.pop()]
            _current_dealer_hand[:] = dealer_hand  # 供道具系统使用
    
            # ===== 发牌通知 =====
            _current_hands = dict(hands)  # 同步到全局供道具使用
            _current_deck  = deck
            print(f"[服务器] 发牌: {[(names.get(p,'?'), hands[p]) for p in current_players]}")
            for p in current_players:
                send(p, f"[HAND]{hands[p]}|{calc(hands[p])}")
                print(f"[服务器] 发送 HAND 给 {names.get(p,'?')}: {hands[p]}")
    
            dealer_upcard = dealer_hand[1]
            broadcast_all(f"[INFO]庄家明牌: {dealer_upcard}")
    
            # 给观战者发送所有人的牌（观战可以看到所有牌）
            for p in current_players:
                pname = names.get(p,'?')
                broadcast_spectators(f"[INFO]{pname} 手牌: {hands[p]}（{calc(hands[p])}点）")
    
            # ===== BlackJack 检测（含极速局：A+6=17也算BJ）=====
            player_bj = {p: is_blackjack_event(hands[p], current_event) for p in non_bankers}
            dealer_bj = is_blackjack_event(dealer_hand, current_event)
    
            if not dealer_is_human and is_ten(dealer_upcard) and is_ace(dealer_hand[0]):
                dealer_bj = True
                broadcast_all(f"[INFO]🃏 庄家BlackJack！暗牌: {dealer_hand[0]}")
    
            # ===== 保险阶段 =====
            insurance_bets = {}
            if not dealer_is_human and is_ace(dealer_upcard):
                broadcast("[INSURANCE]")
                broadcast_spectators("[INFO]保险阶段...")
                ins_results = {}
    
                def collect_ins(p):
                    if bets.get(p, 0) <= 0:
                        ins_results[p] = False; return
                    val = recv_from_queue(p, timeout=20)
                    ins_results[p] = (val in ("1", "[BUY_INS]"))
    
                it = [threading.Thread(target=collect_ins, args=(p,)) for p in non_bankers]
                for t in it: t.start()
                for t in it: t.join()
    
                for p in non_bankers:
                    if ins_results.get(p, False):
                        ins_bet = bets.get(p, 0) // 2
                        if money.get(p, 0) >= ins_bet > 0:
                            money[p] = money.get(p, 0) - ins_bet
                            insurance_bets[p] = ins_bet
                            send(p, f"[INFO]购买保险 {ins_bet} 筹码")
    
                if dealer_bj:
                    broadcast_all(f"[INFO]🃏 庄家有BlackJack！暗牌: {dealer_hand[0]}")
                    for p in non_bankers:
                        if p in insurance_bets:
                            gain = insurance_bets[p] * 2
                            money[p] = money.get(p, 0) + gain
                            send(p, f"[INFO]保险赔付 {gain} 筹码")
                    for p in non_bankers:
                        if player_bj.get(p):
                            refund = bets.get(p, 0)
                            money[p] = money.get(p, 0) + refund
                            send(p, f"[RESULT]0|{money[p]}|🤝 双BJ平局")
                        else:
                            send(p, f"[RESULT]0|{money[p]}|😞 庄家BJ，输")
                    broadcast_all("[INFO]本局结束（庄家BlackJack）")
                    time.sleep(3)
                    # 本局结束，观战者转为正式玩家
                    _promote_spectators()
                    continue
                else:
                    broadcast_all("[INFO]庄家没有BlackJack，保险失效，游戏继续")
    
            # ===== BJ 直接结算 =====
            settled = set()
            for p in non_bankers:
                if player_bj[p]:
                    if dealer_bj:
                        refund = bets.get(p, 0)
                        money[p] = money.get(p, 0) + refund
                        send(p, f"[RESULT]0|{money[p]}|🤝 双BJ平局")
                    else:
                        win = int(bets.get(p, 0) * 2.5)
                        money[p] = money.get(p, 0) + win
                        send(p, f"[RESULT]{win}|{money[p]}|🎉 BlackJack！赢1.5倍")
                        if dealer_is_human and banker in players:
                            money[banker] = money.get(banker, 0) - (win - bets.get(p,0))
                    settled.add(p)
                    broadcast_all(f"[INFO]🃏 {names.get(p,'?')} BlackJack！")
                elif dealer_bj and not dealer_is_human:
                    send(p, f"[RESULT]0|{money[p]}|😞 庄家BJ，输")
                    settled.add(p)
    
            if dealer_bj and not dealer_is_human:
                broadcast_all("[INFO]本局结束（庄家BlackJack）")
                time.sleep(3)
                _promote_spectators()
                continue
    
            active = [p for p in non_bankers if p not in settled]
            random.shuffle(active)  # 每局随机操作顺序
            order_str = " → ".join(names.get(p,'?') for p in active)
            broadcast_all(f"[INFO]本局操作顺序: {order_str}")
    
            # ===== 闲家回合 =====
            all_hands  = {}
            all_bets   = {}
            all_splitbj= {}
            for p in active:
                with lock:
                    if p not in players: continue
                try:
                    h, b, sbj = play_hand(p, hands[p], deck, current_players,
                                          bets.get(p, 0),
                                          allow_double=True, allow_split=True,
                                          allow_surrender=True)
                    all_hands[p]   = h
                    all_bets[p]    = b
                    all_splitbj[p] = sbj
                except Exception as _pe:
                    print(f"[play_hand 异常] {names.get(p,'?')}: {_pe}")
                    import traceback; traceback.print_exc()
                    all_hands[p]   = [hands[p]]
                    all_bets[p]    = [bets.get(p,0)]
                    all_splitbj[p] = False
    
            # ===== 庄家回合 =====
            if dealer_is_human:
                broadcast_all(f"[INFO]庄家 {names.get(banker,'?')} 开始操作")
                for other in current_players:
                    if other != banker:
                        send(other, f"[WAITING_FOR]{names.get(banker,'?')}")
                broadcast_spectators(f"[WAITING_FOR]{names.get(banker,'?')}")
                send(banker, "[WAITING_FOR]")
                send(banker, f"[HAND]{dealer_hand}|{calc(dealer_hand)}")
                dh, _, _ = play_hand(banker, dealer_hand, deck, current_players,
                                     0, allow_double=False, allow_split=False,
                                     allow_surrender=False, force_hit_below=16)
                dealer_hand = dh[0] if dh else dealer_hand
            else:
                broadcast_all(f"[INFO]庄家翻开暗牌: {dealer_hand[0]}")
                while True:
                    d_val_now, d_bust_now = apply_event_to_calc(dealer_hand, current_event)
                    if d_bust_now: break                                    # 已爆停止
                    if not dealer_should_hit_event(dealer_hand, current_event): break  # 达到停牌线
                    card = deck.pop()
                    dealer_hand.append(card)
                    dv_show = calc(dealer_hand)
                    broadcast_all(f"[INFO]庄家摸牌: {card}，点数: {dv_show}")
    
            d_val, d_bust = apply_event_to_calc(dealer_hand, current_event)
            broadcast_all(f"[INFO]庄家最终点数: {d_val}{'（爆牌）' if d_bust else ''}")
    
            # ===== 结算 =====
            if dealer_is_human and banker in players:
                banker_chips = money.get(banker, 0)
                results = {}
                for p in active:
                    if p not in players: continue
                    for i, (h, b) in enumerate(zip(all_hands.get(p,[]), all_bets.get(p,[]))):
                        if not h: continue
                        p_val, p_bust = apply_event_to_calc(h, current_event)
                        is_fcc = is_five_card_charlie(h)
                        if p_bust:
                            results[(p,i)] = ("lose", b, 0)
                        elif is_fcc or d_bust or p_val > d_val:
                            results[(p,i)] = ("win", b, b*2)
                        elif p_val == d_val:
                            results[(p,i)] = ("tie", b, b)
                        else:
                            results[(p,i)] = ("lose", b, 0)
    
                net_win = sum(b for (outcome,b,_) in results.values() if outcome=="win")
                net_lose= sum(b for (outcome,b,_) in results.values() if outcome=="lose")
                net_pay = net_win - net_lose
                if net_pay > banker_chips:
                    broadcast_all(f"[INFO]💸 爆庄！庄家筹码不足，按比例赔付")
                    ratio = banker_chips / net_pay if net_pay > 0 else 0
                else:
                    ratio = 1.0
    
                for (p, i), (outcome, bet_amt, gain) in results.items():
                    label = f"手牌{i+1} " if len(all_hands.get(p,[])) > 1 else ""
                    pname2 = names.get(p,'?')
                    if outcome == "win":
                        actual_gain = int(bet_amt + bet_amt * ratio)
                        money[p] = money.get(p, 0) + actual_gain
                        money[banker] = money.get(banker, 0) - int(bet_amt * ratio)
                        send(p, f"[RESULT]{actual_gain}|{money[p]}|{label}🎉 赢了")
                        check_bounty(pname2)
                        update_leaderboard_chips(pname2, money[p])
                    elif outcome == "tie":
                        money[p] = money.get(p, 0) + bet_amt
                        send(p, f"[RESULT]{bet_amt}|{money[p]}|{label}🤝 平局")
                        update_leaderboard_chips(pname2, money[p])
                    else:
                        money[banker] = money.get(banker, 0) + bet_amt
                        send(p, f"[RESULT]0|{money[p]}|{label}😞 输了")
                        update_loss_streak(pname2)
                        update_leaderboard_chips(pname2, money[p])
                    broadcast_spectators(f"[INFO]{names.get(p,'?')} {label}结算完毕，余额: {money[p]}")
    
                send(banker, f"[RESULT]0|{money[banker]}|🎰 庄家结算完毕")
                send(banker, f"[INFO]庄家结算完毕，当前筹码: {money[banker]}")
                bkname = names.get(banker,'?')
                update_leaderboard_chips(bkname, money[banker])
            else:
                import shop as _shop
                # 时空悖论：结算前揭开盲牌
                for pp, blind_card in list(_paradox_blind_card.items()):
                    ppname = names.get(pp,"?")
                    all_hands.setdefault(pp, [[]])
                    if all_hands[pp]:
                        all_hands[pp][0].append(blind_card)
                        bv = calc(all_hands[pp][0])
                        send(pp, f"[HAND]{all_hands[pp][0]}|{bv}")
                        broadcast_all(f"[INFO]⚡ 时空悖论揭晓！{ppname} 的盲抽暗牌是 {blind_card}，点数: {bv}")
                        if bv > 21:
                            # 二次爆牌：双倍扣注
                            extra = all_bets.get(pp,[0])[0]
                            money[pp] = money.get(pp,0) - extra
                            broadcast_all(f"[INFO]💀 时空惩罚！{ppname} 二次爆牌，额外扣除 {extra} 筹码！")
                _paradox_blind_card.clear()
    
                for p in active:
                    if p not in players: continue
                    for i, (h, b) in enumerate(zip(all_hands.get(p,[]), all_bets.get(p,[]))):
                        if not h: continue
                        pname3 = names.get(p,'?')
                        p_val  = calc(h)
                        is_fcc = is_five_card_charlie(h)
                        label  = f"手牌{i+1} " if len(all_hands.get(p,[])) > 1 else ""
                        mult   = _gamble_multiplier.get(p, 1.0)  # 搏命契约倍率
    
                        # ===== 点数修正（被动）=====
                        pd3 = _shop.get_player_data(pname3)
                        if pd3.get("items",{}).get("点数修正",0) > 0:
                            # 检查 ±1 能否改变结果
                            for delta in [+1, -1]:
                                adj_val = p_val + delta
                                if 0 < adj_val <= 21:
                                    if (not d_bust and adj_val > d_val) or d_bust:
                                        if p_val > 21 or p_val <= d_val:
                                            p_val = adj_val
                                            items3 = pd3["items"]
                                            items3["点数修正"] -= 1
                                            if items3["点数修正"] <= 0: del items3["点数修正"]
                                            _shop.save_player_data(pname3, {"items": items3})
                                            send(p, f"[INFO]📏 点数修正触发！点数从{calc(h)}调整为{p_val}")
                                            send(p, "[ITEM_USED]点数修正")
                                            break
    
                        # ===== 结算 =====
                        if p_val > 21:
                            gain, msg = 0, "💸 爆牌输"
                            # 金蝉脱壳（被动）：输或爆牌不扣注
                            pd3b = _shop.get_player_data(pname3)
                            if pd3b.get("items",{}).get("金蝉脱壳",0) > 0:
                                gain = b  # 退还赌注
                                msg  = "🛡 金蝉脱壳！爆牌不扣注"
                                items3b = pd3b["items"]
                                items3b["金蝉脱壳"] -= 1
                                if items3b["金蝉脱壳"] <= 0: del items3b["金蝉脱壳"]
                                _shop.save_player_data(pname3, {"items": items3b})
                                send(p, "[INFO]🛡 金蝉脱壳触发！本局不扣下注筹码")
                                send(p, "[ITEM_USED]金蝉脱壳")
                        elif is_fcc:
                            gain, msg = int(b * 2 * mult), "🐉 五龙！赢2倍"
                        elif d_bust or p_val > d_val:
                            gain, msg = int(b * 2 * mult), "🎉 赢了"
                            if mult > 1: msg = f"🎉 赢了（搏命×{mult}）"
                        elif p_val == d_val:
                            gain, msg = b, "🤝 平局"
                        else:
                            gain, msg = 0, "😞 输了"
                            # 金蝉脱壳：输也不扣注
                            pd3c = _shop.get_player_data(pname3)
                            if pd3c.get("items",{}).get("金蝉脱壳",0) > 0:
                                gain = b
                                msg  = "🛡 金蝉脱壳！输了不扣注"
                                items3c = pd3c["items"]
                                items3c["金蝉脱壳"] -= 1
                                if items3c["金蝉脱壳"] <= 0: del items3c["金蝉脱壳"]
                                _shop.save_player_data(pname3, {"items": items3c})
                                send(p, "[INFO]🛡 金蝉脱壳触发！本局不扣下注筹码")
                                send(p, "[ITEM_USED]金蝉脱壳")
                            elif mult > 1 and gain == 0:
                                # 搏命契约输了额外扣（本金已在下注时扣过，这里只扣额外部分）
                                extra = int(b * (mult - 1))
                                actual_extra = min(extra, money.get(p, 0))  # 不超过现有筹码
                                money[p] = money.get(p,0) - actual_extra
                                gain = -actual_extra
                                msg = f"😞 输了（搏命×{mult}，额外扣{actual_extra}）"

                        # gain已包含搏命额外扣款，直接加（普通输/赢情况）
                        if not (mult > 1 and gain < 0):  # 搏命损失已在上面处理
                            money[p] = max(0, money.get(p, 0) + gain)
                        else:
                            money[p] = max(0, money.get(p, 0))  # 确保不为负
                        send(p, f"[RESULT]{gain}|{money[p]}|{label}{msg}")
                        send(p, f"[INFO]{label}{msg}，获得 {gain}，余额: {money[p]}")
                        broadcast_spectators(f"[INFO]{pname3} {label}{msg}")
                        money[p] = max(0, money.get(p, 0))  # 保证不为负
                        update_leaderboard_chips(pname3, money[p])
                        if gain > b: check_bounty(pname3)
                        elif gain == 0: update_loss_streak(pname3)
    
            # ===== P4: 灵魂链接结算 =====
            _game_phase = "settle"
            if _soul_link:
                for linker, target in list(_soul_link.items()):
                    if linker not in money or target not in money: continue
                    lname = names.get(linker,"?"); tname2 = names.get(target,"?")
                    # 检查目标是否赢了
                    target_gain = 0
                    target_bust = False
                    for ph, pb in zip(all_hands.get(target,[]), all_bets.get(target,[])):
                        if ph and calc(ph) <= 21 and (d_bust or calc(ph) > d_val):
                            target_gain += pb
                        elif ph and calc(ph) > 21:
                            target_bust = True
                    if target_bust:
                        # 目标爆牌，灵魂链接者也爆
                        penalty = min(money.get(linker,0)//2, 500)
                        money[linker] = money.get(linker,0) - penalty
                        send(linker, f"[INFO]🔗 灵魂链接！{tname2} 爆牌，你受到连坐扣除 {penalty} 筹码")
                        broadcast_all(f"[INFO]🔗 {lname} 被灵魂链接连坐！")
                    elif target_gain > 0:
                        share = target_gain // 4  # 分25%
                        money[linker] = money.get(linker,0) + share
                        send(linker, f"[INFO]🔗 灵魂链接！{tname2} 赢了，你分得 {share} 筹码！")
                        broadcast_all(f"[INFO]🔗 {lname} 通过灵魂链接获得 {share} 筹码！")
    
            # ===== 外围下注结算 =====
            for bettor_p, sbet in list(_side_bets.items()):
                target3  = sbet["target"]
                btype3   = sbet["type"]
                bamt3    = sbet["amount"]
                tname3   = names.get(target3,"?")
                bname3   = names.get(bettor_p,"?")
                if target3 not in current_players: continue
                tv3 = calc(hands.get(target3,[[]]) if isinstance(hands.get(target3),list) and hands.get(target3) and isinstance(hands.get(target3)[0],list) else [hands.get(target3,[])])
                try:
                    flat = hands.get(target3,[])
                    tv3  = calc(flat) if flat and isinstance(flat[0],str) else calc(flat[0]) if flat else 0
                except: tv3 = 0
                t_busted = tv3 > 21
                t_won    = tv3 <= 21 and (d_bust or tv3 > d_val)
                correct  = (btype3=="bust" and t_busted) or (btype3=="win" and t_won)
                if correct:
                    win_amt = bamt3 * 2
                    money[bettor_p] = money.get(bettor_p,0) + win_amt
                    send(bettor_p, f"[INFO]🎲 外围押注命中！{tname3}{'爆牌' if btype3=='bust' else '赢了'}！赢得{win_amt}！")
                    broadcast_all(f"[INFO]🎲 {bname3}外围押注命中，赢{win_amt}筹码！")
                else:
                    send(bettor_p, f"[INFO]🎲 外围押注未中，损失{bamt3}筹码")
            _side_bets.clear()
    
            # ===== 吸血印记结算 =====
            for victim_p, vampire_p in list(_vampire_mark.items()):
                if victim_p not in current_players or vampire_p not in current_players: continue
                try:
                    vflat = hands.get(victim_p,[])
                    vv3   = calc(vflat) if vflat and isinstance(vflat[0],str) else 0
                except: vv3 = 0
                v_won3 = vv3 <= 21 and (d_bust or vv3 > d_val)
                if v_won3:
                    drain3 = int(bets.get(victim_p,0) * 0.20)
                    if drain3 > 0:
                        money[victim_p]  = money.get(victim_p,0)  - drain3
                        money[vampire_p] = money.get(vampire_p,0) + drain3
                        send(victim_p,  f"[INFO]🧛 {names.get(vampire_p,'?')}吸血，扣走你{drain3}筹码！")
                        send(vampire_p, f"[INFO]🧛 吸血成功！从{names.get(victim_p,'?')}吸取{drain3}筹码！")
            _vampire_mark.clear()
    
            broadcast_all("[INFO]本局结束")
    
            # ===== 悬赏结算 =====
            # (简化：根据result消息中有"赢"的玩家更新连胜)
            # 实际连胜统计在结算时更新，这里只广播当前悬赏目标
            if bounty_target:
                broadcast_all(f"[BOUNTY]{bounty_target}")
    
            time.sleep(3)
        except Exception as _loop_ex:
            import traceback
            print(f"[单局异常] {_loop_ex}")
            traceback.print_exc()
            game_running = False

        # ===== 本局结束：观战者转为正式玩家 =====
        _promote_spectators()

def _promote_spectators():
    """将所有观战者转为正式玩家，加入下一局"""
    global game_running
    game_running = False
    with lock:
        promoted = spectators[:]
        spectators.clear()
        for p in promoted:
            ready[p] = False
            players.append(p)
    if promoted:
        names_str = "、".join(names.get(p,'?') for p in promoted)
        broadcast_all(f"[INFO]👤 {names_str} 加入下一局！")
        broadcast_lobby_status()

# ===== 接收玩家连接 =====
def accept_players(server):
    while True:
        conn, addr = server.accept()
        try:
            send(conn, "[NAME]")
            conn.settimeout(10)
            raw = conn.recv(1024).decode().strip()
            if "|" in raw:
                parts = raw.split("|", 1)
                name  = parts[0].strip() or f"玩家{random.randint(100,999)}"
                try:    starting_chips = int(parts[1])
                except: starting_chips = 1500
            else:
                name  = raw or f"玩家{random.randint(100,999)}"
                starting_chips = 1500
        except:
            name  = f"玩家{random.randint(100,999)}"
            starting_chips = 1500

        with lock:
            names[conn]      = name
            money[conn]      = starting_chips
            ready[conn]      = False
            msg_queues[conn] = queue.Queue()

            if game_running:
                # 游戏进行中，加入观战
                spectators.append(conn)
                is_spec = True
            else:
                players.append(conn)
                is_spec = False

        if is_spec:
            print(f"{name} 加入观战，筹码: {starting_chips}")
            send(conn, "[SPECTATING]")
            broadcast_all(f"[INFO]👁 {name} 加入观战")
        else:
            print(f"{name} 加入，筹码: {starting_chips}，人数: {len(players)}")
            broadcast(f"[INFO]👤 {name} 加入了游戏")

        broadcast_lobby_status()
        # 初始化排行榜筹码
        leaderboard["chips"][name] = starting_chips
        broadcast_leaderboard()
        threading.Thread(target=player_recv_thread, args=(conn,), daemon=True).start()

# ========================================
# ===== 道具 / 悬赏 / 随机事件 扩展 =====
# ========================================

def broadcast_leaderboard():
    import json
    data = json.dumps(leaderboard, ensure_ascii=False)
    broadcast_all(f"[LEADERBOARD]{data}")

def pick_event():
    global current_event, game_count
    game_count += 1
    if game_count % EVENT_INTERVAL == 0:
        events = [k for k in EVENTS if k != "normal"]
        current_event = random.choice(events)
    else:
        current_event = "normal"
    return current_event

def update_leaderboard_chips(name, chips):
    """更新筹码榜"""
    leaderboard["chips"][name] = chips
    broadcast_leaderboard()

def check_bounty(winner_name):
    """更新连胜，同时更新连胜榜"""
    global bounty_target, win_streaks, loss_streaks
    win_streaks[winner_name]  = win_streaks.get(winner_name, 0) + 1
    loss_streaks[winner_name] = 0  # 赢了重置连败
    # 更新历史最高连胜
    cur_best = leaderboard["win_streak"].get(winner_name, 0)
    if win_streaks[winner_name] > cur_best:
        leaderboard["win_streak"][winner_name] = win_streaks[winner_name]
    if win_streaks[winner_name] >= BOUNTY_STREAK:
        bounty_target = winner_name
        return winner_name
    return None

def update_loss_streak(loser_name):
    """更新连败，同时更新连败榜"""
    global win_streaks, loss_streaks
    loss_streaks[loser_name] = loss_streaks.get(loser_name, 0) + 1
    win_streaks[loser_name]  = 0  # 败了重置连胜
    global bounty_target
    if bounty_target == loser_name:
        bounty_target = None
    # 更新历史最高连败
    cur_best = leaderboard["loss_streak"].get(loser_name, 0)
    if loss_streaks[loser_name] > cur_best:
        leaderboard["loss_streak"][loser_name] = loss_streaks[loser_name]

def reset_streak(loser_name):
    win_streaks[loser_name] = 0
    global bounty_target
    if bounty_target == loser_name:
        bounty_target = None



def get_dealer_upcard_for_peek(dealer_hand):
    return dealer_hand[0]  # 暗牌（索引0）

def start():
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', 5555))
    server.listen()
    print("服务器启动...")
    threading.Thread(target=accept_players, args=(server,), daemon=True).start()
    try:
        game_loop()
    except Exception as _e:
        import traceback
        print(f"[服务器崩溃] {_e}")
        traceback.print_exc()

if __name__ == "__main__":
    start()
