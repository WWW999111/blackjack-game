import pygame
import socket
import threading
import random
import math
import json
import os
import sys
import importlib.util

def _import_from_file(module_name, file_path):
    """从绝对路径导入模块，每次强制重新加载"""
    # 先删除旧缓存，确保重新执行
    if module_name in sys.modules:
        del sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod  = importlib.util.module_from_spec(spec)
    # 注意：先不加入 sys.modules，执行完再加入，避免循环导入时拿到半成品
    spec.loader.exec_module(mod)
    sys.modules[module_name] = mod
    return mod

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ===== 大数字格式化 =====
_UNITS = [
    (10**33, "Dc"), (10**30, "No"), (10**27, "Oc"), (10**24, "Sp"),
    (10**21, "Sx"), (10**18, "Qi"), (10**15, "Qa"), (10**12, "T"),
    (10**9,  "B"),  (10**6,  "M"),
]

def fmt_chips(n):
    """把大数字格式化，从百万（1,000,000）起才转换单位"""
    try:
        n = int(n)
    except:
        return str(n)
    if abs(n) < 1_000_000:
        # 小于百万直接显示原始数字，加千位分隔符
        return f"{n:,}"
    for threshold, suffix in _UNITS:
        if abs(n) >= threshold:
            val = n / threshold
            if val == int(val):
                return f"{int(val)}{suffix}"
            return f"{val:.2f}".rstrip('0').rstrip('.') + suffix
    return f"{n:,}"

def parse_bet_input(s):
    """把用户输入的下注字符串（含E/K/M等）解析为整数"""
    s = s.strip().upper()
    if not s: return 0
    # E notation: 1E6, 5.2E15
    import re
    m = re.match(r'^([0-9.]+)[Ee]([0-9]+)$', s)
    if m:
        try: return int(float(m.group(1)) * 10**int(m.group(2)))
        except: pass
    # Suffix notation
    suffix_map = {
        'DC':10**33,'NO':10**30,'OC':10**27,'SP':10**24,
        'SX':10**21,'QI':10**18,'QA':10**15,'T':10**12,
        'B':10**9,'M':10**6,'K':10**3,
    }
    for suf, mul in suffix_map.items():
        if s.endswith(suf):
            try: return int(float(s[:-len(suf)]) * mul)
            except: pass
    try: return int(float(s))
    except: return 0

_items_mod   = _import_from_file("items",   os.path.join(_SCRIPT_DIR, "items.py"))
_shop_mod    = _import_from_file("shop",    os.path.join(_SCRIPT_DIR, "shop.py"))
_effects_mod = _import_from_file("effects", os.path.join(_SCRIPT_DIR, "effects.py"))

ITEMS        = _items_mod.ITEMS
CARD_BACKS   = _items_mod.CARD_BACKS
TABLECLOTHS  = _items_mod.TABLECLOTHS
ACHIEVEMENTS = _items_mod.ACHIEVEMENTS
EVENTS       = _items_mod.EVENTS
TITLES       = _items_mod.TITLES
Shop         = _shop_mod
draw_card_effect = _effects_mod.draw_card_effect

pygame.init()

WIDTH, HEIGHT = 1100, 720
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("♠ BlackJack 21点对战")

# 开启输入法支持
pygame.key.start_text_input()

# 压制 libpng iCCP 警告（在 display 初始化后立即加载图片）
import os as _os
_os.environ['SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS'] = '0'  # 避免焦点切换问题

# ===== 字体 =====
try:
    font_sm = pygame.font.SysFont("simhei", 18)
    font_md = pygame.font.SysFont("simhei", 22)
    font_lg = pygame.font.SysFont("simhei", 30)
    font_xl = pygame.font.SysFont("simhei", 42)
except:
    font_sm = pygame.font.SysFont(None, 18)
    font_md = pygame.font.SysFont(None, 22)
    font_lg = pygame.font.SysFont(None, 30)
    font_xl = pygame.font.SysFont(None, 42)

# ===== 颜色 =====
C_BG       = (15, 40, 25)
C_TABLE    = (22, 90, 50)
C_TABLE2   = (18, 70, 40)
C_FELT     = (25, 105, 58)
C_GOLD     = (212, 175, 55)
C_GOLD2    = (255, 215, 80)
C_WHITE    = (255, 255, 255)
C_RED      = (200, 40, 40)
C_RED2     = (230, 60, 60)
C_GREEN2   = (80, 220, 110)
C_GRAY     = (160, 160, 160)
C_DARKGRAY = (60, 60, 60)
C_PANEL    = (10, 28, 18)
C_READY    = (40, 160, 80)
C_READY2   = (60, 200, 100)
C_UNREADY  = (160, 60, 40)
C_CYAN     = (80, 200, 200)
C_YELLOW   = (255, 230, 60)
C_ORANGE   = (200, 120, 40)

# ===== 路径 =====
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
PNG_DIR   = os.path.join(BASE_DIR, "PNG")
SAVE_FILE = os.path.join(BASE_DIR, "save.json")
BONUS_PER_SESSION = 1500
SOLO_RELIEF_AMOUNT    = 10000  # 人机模式救济金
SOLO_RELIEF_MAX_DAILY = 5      # 每日最多5次

CARD_W = 90
CARD_H = 126

# ===== 图片加载 =====
SUIT_MAP = {'♥': 'Heart', '♦': 'Diamond', '♠': 'Spade', '♣': 'Club'}
RANK_MAP = {'A':'A','J':'J','Q':'Q','K':'K',
            '2':'2','3':'3','4':'4','5':'5','6':'6',
            '7':'7','8':'8','9':'9','10':'10'}
card_images      = {}
bg_image         = None
card_back_cache  = {}   # 卡背图片缓存，避免每帧重复加载

# ===== 固定牌->卡背映射（seed=42，所有玩家相同）=====
def _build_card_back_map():
    """根据已购买的卡背随机分配给52张牌（没买=空映射，显示默认卡背）"""
    import random as _r
    _suits = ['♠','♥','♦','♣']
    _ranks = ['A','2','3','4','5','6','7','8','9','10','J','Q','K']
    _cards = [s+r for s in _suits for r in _ranks]
    owned = [b for b in my_owned_backs if b in CARD_BACKS]
    if not owned:
        return {}   # 没买卡背，所有牌用默认卡背
    # 把已购买的卡背循环分配给52张牌（重复使用）
    _r.shuffle(owned)
    mapping = {}
    for i, card in enumerate(_cards):
        mapping[card] = owned[i % len(owned)]
    return mapping

# 在 CARD_BACKS 加载后初始化（见 main() 里 load_images 之后）
CARD_BACK_MAP = {}  # {card_str: back_name}

# ===== 翻牌动画队列 =====
# 每个元素: {"card": card_str, "x": x, "y": y, "w": w, "h": h,
#            "tick": 0, "duration": 40, "callback": fn}
card_reveal_queue = []  # 待播放的翻牌动画
card_reveal_pending = []  # [(card_str, x, y, w, h, delay_frames)]

def load_images():
    global bg_image
    bp = os.path.join(PNG_DIR, "Background.png")
    if os.path.exists(bp):
        try:
            bg_image = pygame.transform.scale(pygame.image.load(bp).convert(), (WIDTH, HEIGHT))
        except: pass
    for ss, sn in SUIT_MAP.items():
        for rs, rn in RANK_MAP.items():
            p = os.path.join(PNG_DIR, f"{sn}{rn}.png")
            if os.path.exists(p):
                try:
                    card_images[ss+rs] = pygame.transform.smoothscale(
                        pygame.image.load(p).convert_alpha(), (CARD_W, CARD_H))
                except: pass
    # 预加载所有卡背图片到缓存
    card_back_dir = os.path.join(BASE_DIR, "Card Back Visual")
    if os.path.exists(card_back_dir):
        for fname in os.listdir(card_back_dir):
            if fname.lower().endswith(".png"):
                back_name = fname[:-4]
                fpath = os.path.join(card_back_dir, fname)
                try:
                    raw = pygame.image.load(fpath).convert_alpha()
                    card_back_cache[f"{back_name}_{CARD_W}_{CARD_H}"] =                         pygame.transform.smoothscale(raw, (CARD_W, CARD_H))
                except: pass

# load_images() 在 pygame.display.set_mode() 后调用，见 main()
# CARD_BACK_MAP 在 load_images() 后通过 _build_card_back_map() 初始化

# ===== 音乐系统 =====
SOUNDTRACK_DIR = os.path.join(BASE_DIR, "Soundtrack")

BGM_MAP = {
    "lobby":     "1 Main Theme.mp3",
    "grabbing":  "3 Tarot Pack Theme.mp3",
    "betting":   "2 Shop Theme.mp3",
    "game":      "4 Planet Pack Theme.mp3",
    "result":    "5 Boss Blind Theme.mp3",
}

current_bgm = ""

def play_bgm(key):
    """播放指定场景的背景音乐，已在播放则不重复"""
    global current_bgm
    if key == current_bgm:
        return
    filename = BGM_MAP.get(key, "")
    if not filename:
        return
    path = os.path.join(SOUNDTRACK_DIR, filename)
    if not os.path.exists(path):
        return
    try:
        pygame.mixer.music.load(path)
        pygame.mixer.music.set_volume(0.0)
        pygame.mixer.music.play(-1)  # -1 = 循环播放
        current_bgm = key
    except:
        pass

def stop_bgm():
    global current_bgm
    try:
        pygame.mixer.music.fadeout(500)
    except:
        pass
    current_bgm = ""

# 初始化音频
try:
    pygame.mixer.init()
    mixer_ok = True
except:
    mixer_ok = False

# ===== 存档（同时存筹码、名字、IP）=====
def load_save():
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {}

def save_full(data):
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_record(name, chips):
    """存档筹码：单人模式存 players，联机模式存 multi_players"""
    data = load_save()
    if "players" not in data:
        data["players"] = {}
    # 单人模式（solo_submode有效时）存单人存档
    # 联机结算时 game_mode=="multi" 存联机存档
    if game_mode == "multi":
        if "multi_players" not in data:
            data["multi_players"] = {}
        data["multi_players"][name] = chips
    else:
        data["players"][name] = chips
    save_full(data)

def get_starting_chips(name):
    """联机模式：每日首次登录+1500补贴，返回当前筹码"""
    import datetime
    data    = load_save()
    players = data.get("players", {})
    today   = datetime.date.today().isoformat()
    logins  = data.get("daily_logins", {})
    is_new  = name not in players  # 是否新玩家

    # 联机模式用独立的 multi_chips 存档，不污染单人存档
    multi_players = data.get("multi_players", {})
    chips = multi_players.get(name, players.get(name, 0))  # 兼容旧存档

    if logins.get(name) != today:
        chips += BONUS_PER_SESSION
        logins[name] = today
        data["daily_logins"] = logins
        if "multi_players" not in data:
            data["multi_players"] = {}
        data["multi_players"][name] = chips
        save_full(data)

    if is_new or name not in multi_players:
        return max(chips, BONUS_PER_SESSION)
    return chips

def load_profile():
    """读取上次保存的名字和IP，返回 (name, ip) 或 (None, None)"""
    data = load_save()
    name = data.get("last_name", "")
    ip   = data.get("last_ip", "")
    return name, ip

def save_profile(name, ip):
    data = load_save()
    data["last_name"] = name
    data["last_ip"]   = ip
    save_full(data)

# ===== 网络 =====
client = socket.socket()

# ===== 游戏状态 =====
hand          = []
money         = 0
result        = ""
result_gain   = 0
log           = []
my_turn       = False
bet_mode      = False
bet_submitted = False   # 已提交下注，等待其他玩家
is_ready      = False
waiting_for   = ""
in_lobby      = True
total_players = 0
ready_players = 0
countdown     = 60
game_started  = False
input_text    = ""
my_name       = ""
server_ip     = "127.0.0.1"
anim_tick     = 0

# screen_state: "menu" | "name_input" | "lobby" | "grabbing" | "prep" | "game" | "insurance" | "solo"
screen_state    = "menu"
grabbing_done    = False
# 道具准备阶段
prep_phase       = False   # 是否在道具准备阶段
prep_active      = ""      # 选择的主动道具
prep_passive     = ""      # 选择的被动道具
prep_confirmed   = False   # 是否已确认
prep_start_time  = 0        # prep开始的 anim_tick（用于倒计时）
banker_name     = ""
available_opts  = []    # 当前可用操作列表 ["HIT","STAND","DOUBLE","SPLIT","SURRENDER"]
insurance_done  = False # 是否已选保险
is_banker        = False # 本局是否是庄家
is_spectating    = False # 自己是否在观战
spectator_count  = 0     # 当前观战人数
relief_available = True  # 是否可以申请救济金

# 输入界面字段（名字 / IP 各自独立）
fi_name       = ""   # 输入框内容：名字
fi_ip         = ""   # 输入框内容：IP
fi_focus      = "name"  # 当前聚焦框："name" | "ip"

# 大厅里"修改信息"弹窗
show_edit     = False
edit_name     = ""
edit_ip       = ""
edit_focus    = "name"

# ===== 新系统状态 =====
# 道具
my_items       = {}    # {"透视眼镜":1, ...}
item_used      = {}    # 本局已使用的道具 {item_name: True}
active_used_count  = 0  # 本局已用主动道具数
passive_used_count = 0  # 本局已用被动道具数
peek_result      = ""   # 透视眼镜看到的暗牌
dealer_peek_hand  = []   # 透视后显示的庄家完整手牌
dealer_visible    = []   # 多人模式庄家可见手牌（明牌+已翻开的牌）
dealer_upcard_str = ""   # 庄家明牌字符串
is_blinded       = False  # 被致盲烟雾
paradox_ready    = False
paradox_active   = False
game_phase       = "idle"
lucky_buff_active = False
lucky_buff_games  = 0
# ===== 新玩法状态 =====
silence_field    = False   # 沉默干扰器：本局主动道具全禁
doom_beacon_set  = False   # 厄运信标已激活
blood_moon_active= False   # 血月之夜
tornado_active   = False   # 龙卷风
# 目标选择弹窗
target_select_mode  = False   # 是否显示目标选择弹窗
target_select_item  = ""      # 正在选择目标的道具名
target_select_cb    = None    # 选择后的回调（发送消息）
# 外围下注
side_bet_mode    = False   # 是否在外围下注选择中
side_bet_target  = ""      # 目标玩家名
side_bet_type    = ""      # bust/win
side_bet_input   = ""      # 金额输入
can_side_bet     = False   # 当前是否可以外围下注（停牌/爆牌后）
# 西部决斗
duel_active      = False   # 决斗进行中
duel_countdown   = 0       # 倒计时
duel_my_card     = ""      # 我的决斗牌
duel_opp_card    = ""      # 对手决斗牌
duel_result      = ""      # 决斗结果  # 当前游戏阶段（同步服务器）
# 外观
my_card_back   = ""    # 当前卡背名
my_tablecloth  = "default"
my_owned_backs = []
my_owned_cloths= ["default"]
my_achievements= []
my_title       = ""
# 悬赏
bounty_name    = ""    # 当前被悬赏的玩家名
# 随机事件
current_event  = "normal"
event_name     = ""
event_announce_tick = 0   # 事件提示动画开始时间
event_announce_dur  = 180 # 显示3秒（60fps×3）
# 商店界面
screen_shop    = False  # 是否显示商店覆盖层
shop_opened_gid = -99  # 上次打开商店时的 game_id
shop_open_token  = 0    # 每次打开商店递增，用于强制刷新道具池
_prev_screen_shop = False  # 上一帧商店是否打开
shop_tab       = "items"  # "items"|"cardbacks"|"tablecloth"|"achievements"
shop_scroll    = 0
# 成就弹窗
new_achievements = []  # 本局新解锁成就列表，用于弹窗
ach_popup_tick   = 0
# 称号设置
show_title_menu  = False

# 排行榜
leaderboard_data = {"chips":{}, "win_streak":{}, "loss_streak":{}}
current_game_id = 0  # 当前游戏局ID，用于库存系统
show_leaderboard = False

# 日志滚动与显示
log_scroll  = 0     # 从底部往上滚动的行数（0=显示最新）
log_visible = False  # Tab 键切换日志显示/隐藏（默认关闭）

# ===== 游戏模式 =====
# "menu" | "name_input" | "lobby" | "grabbing" | "game" | "insurance" | "spectating"
# 单人模式额外状态
game_mode        = "menu"   # "single_normal" | "single_custom" | "multi"
solo_submode     = "normal" # "normal"=共享存档 | "custom"=独立存档
editing_chips    = False   # 自定义模式改筹码弹窗
edit_chips_input = ""      # 改筹码输入框
solo_state       = "idle"   # "betting"|"playing"|"dealer"|"result"
solo_hand        = []
solo_dealer_hand = []
solo_bet         = 0
solo_deck        = []
solo_result_msg  = ""
solo_dealer_upcard_hidden = True  # 庄家暗牌是否隐藏

# ===== 粒子 =====
particles = []

def add_particles(x, y, color, count=12):
    for _ in range(count):
        angle = random.uniform(0, math.pi*2)
        speed = random.uniform(2, 6)
        particles.append({'x':x,'y':y,
            'vx':math.cos(angle)*speed,'vy':math.sin(angle)*speed,
            'life':1.0,'color':color,'size':random.randint(3,7)})

def update_particles():
    global particles
    for p in particles:
        p['x']+=p['vx']; p['y']+=p['vy']; p['vy']+=0.15; p['life']-=0.04
    particles=[p for p in particles if p['life']>0]

def draw_particles():
    for p in particles:
        color=tuple(min(255,c) for c in p['color'])
        size=max(1,int(p['size']*p['life']))
        pygame.draw.circle(screen,color,(int(p['x']),int(p['y'])),size)

# ===== 网络接收 =====
def receive():
    global hand, money, result, result_gain, my_turn, bet_mode
    global in_lobby, total_players, ready_players, countdown
    global game_started, waiting_for, screen_state, grabbing_done, banker_name
    global available_opts, insurance_done, is_banker, relief_available
    global is_spectating, spectator_count
    global bounty_name, current_event, event_name
    global my_items, item_used, peek_result, is_blinded, dealer_peek_hand
    global paradox_ready, paradox_active, game_phase
    global active_used_count, passive_used_count
    global active_used_count, passive_used_count, game_phase
    global leaderboard_data
    global new_achievements, ach_popup_tick
    global my_card_back, my_tablecloth, my_owned_backs, my_owned_cloths
    global my_achievements, my_title
    global silence_field, doom_beacon_set, blood_moon_active, tornado_active
    global dealer_visible, dealer_upcard_str
    global lucky_buff_active, lucky_buff_games, can_side_bet
    global duel_active, duel_countdown, duel_my_card, duel_opp_card, duel_result
    global prep_active, prep_passive, prep_confirmed, prep_start_time, bet_submitted, prep_scroll
    buffer=""
    while True:
        try:
            data=client.recv(2048).decode()
            if not data: break
            buffer+=data
            while "\n" in buffer:
                msg,buffer=buffer.split("\n",1)
                msg=msg.strip()
                if msg.startswith("[HAND]"):
                    hand=eval(msg.replace("[HAND]","").split("|")[0])
                    bet_mode=False; bet_submitted=False  # 收到手牌，下注结束
                    import sys; sys.stdout.flush()
                    if screen_state not in ("game","solo"):
                        screen_state="game"; in_lobby=False; game_started=True
                elif msg.startswith("[BET]"):
                    money=int(msg.replace("[BET]","")); bet_mode=True
                    game_phase="betting"
                    dealer_visible=[]; dealer_upcard_str=""
                    in_lobby=False; game_started=True
                    item_used={}; active_used_count=0; passive_used_count=0
                    # prep阶段保持，等用户确认后切game
                    # 其他非game状态才切换
                    if screen_state not in ("prep","game","solo"):
                        screen_state="game"
                # [TURN] 已被 [OPTIONS] 替代，忽略旧协议
                elif msg.startswith("[WAITING_FOR]"):
                    waiting_for=msg.replace("[WAITING_FOR]","").strip()
                    game_phase="other_turn" if waiting_for and waiting_for!=my_name else "player_turn"
                elif msg.startswith("[LOBBY]"):
                    parts=msg.replace("[LOBBY]","").split("|")
                    total_players=int(parts[0]); ready_players=int(parts[1])
                    if len(parts)>2: countdown=int(parts[2])
                elif msg.startswith("[RELIEF_OK]"):
                    money = int(msg.replace("[RELIEF_OK]",""))
                    relief_available = True
                    add_particles(WIDTH//2, HEIGHT//2, C_GOLD2, 20)
                elif msg=="[RELIEF_FAIL]":
                    relief_available = False
                elif msg=="[SPECTATING]":
                    is_spectating=True; screen_state="spectating"
                elif msg.startswith("[SPECTATE]"):
                    parts=msg.replace("[SPECTATE]","").split("|")
                    spectator_count=int(parts[0])
                elif msg=="[WAITING]":
                    in_lobby=True; screen_state="lobby"
                    game_started=False; result=""; bet_mode=False; bet_submitted=False
                    is_spectating=False; relief_available=True
                    item_used={}; my_turn=False; waiting_for=""
                    # 关闭所有覆盖层，防止按钮失效
                    screen_shop=False; show_leaderboard=False
                    log_visible=False; show_item_panel=False
                    peek_result=""; dealer_peek_hand=[]
                    is_blinded=False; paradox_ready=False; paradox_active=False
                    card_reveal_queue.clear(); card_reveal_pending.clear()
                elif msg=="[GRABBING]":
                    screen_state="grabbing"; grabbing_done=False; banker_name=""
                elif msg.startswith("[BANKER]"):
                    banker_name=msg.replace("[BANKER]","").strip()
                    is_banker = (banker_name == my_name)
                    bstr = "🎰 你是庄家！" if is_banker else f"庄家: {banker_name}"
                    log.append(bstr)
                elif msg.startswith("[OPTIONS]"):
                    available_opts = msg.replace("[OPTIONS]","").split(",")
                    my_turn = True; waiting_for = ""; game_phase = "player_turn"
                elif msg=="[INSURANCE]":
                    screen_state="insurance"; insurance_done=False
                elif msg.startswith("[LEADERBOARD]"):
                    import json as _json
                    try:
                        leaderboard_data.update(_json.loads(msg.replace("[LEADERBOARD]","")))
                    except: pass
                elif msg.startswith("[BOUNTY]"):
                    bounty_name = msg.replace("[BOUNTY]","").strip()
                    if bounty_name:
                        log.append(f"👑 {bounty_name} 被悬赏！击败可得赏金500")
                elif msg.startswith("[EVENT]"):
                    current_event = msg.replace("[EVENT]","").strip()
                    from items import EVENTS
                    ev = EVENTS.get(current_event,{})
                    event_name = ev.get("name","")
                    if event_name:
                        log.append(f"🌪 特殊规则: {event_name}")
                        log.append(ev.get("desc",""))
                        event_announce_tick = anim_tick  # 触发提示动画
                elif msg.startswith("[DEALER_REVEAL]"):
                    # 透视眼镜：庄家完整手牌
                    try:
                        dealer_peek_hand = eval(msg.replace("[DEALER_REVEAL]","").strip())
                        peek_result = str(dealer_peek_hand[0]) if dealer_peek_hand else "?"
                        log.append(f"👁 透视眼镜：庄家翻开暗牌 {dealer_peek_hand[0]}")
                        log.append(f"   庄家完整手牌: {dealer_peek_hand}")
                    except:
                        peek_result = msg.replace("[DEALER_REVEAL]","").strip()
                        log.append(f"👁 庄家暗牌：{peek_result}")
                    log_scroll = 0
                    log_visible = True
                    add_particles(WIDTH//2, 200, (0,255,100), 25)
                elif msg.startswith("[PEEK]"):
                    # 兼容旧协议
                    peek_result = msg[len("[PEEK]"):].strip()
                    log.append(f"👁 庄家暗牌：{peek_result}")
                    log_scroll = 0; log_visible = True
                elif msg.startswith("[ITEM_USED]"):
                    # 服务器通知道具已被消耗（被动触发）
                    iname_used = msg.replace("[ITEM_USED]","").strip()
                    item_used[iname_used] = True
                    if iname_used in my_items and my_items[iname_used] > 0:
                        my_items[iname_used] -= 1
                        if my_items[iname_used] <= 0:
                            del my_items[iname_used]
                elif msg == "[BLINDED]":
                    is_blinded = True
                    log.append("🌫 你被致盲了！看不见自己的点数")
                elif msg == "[PARADOX_READY]":
                    paradox_ready = True
                    log.append("⚡ 时光倒流触发！你有「再来一次」，可触发【时空悖论】Combo！")
                    log.append("   → 点击道具面板中的「再来一次」触发！")
                    log_visible = True; log_scroll = 0
                elif msg == "[PARADOX]":
                    paradox_active = True; paradox_ready = False
                    log.append("⚡ 【时空悖论】触发！盲抽一张命运之牌（你看不见它）...")
                    log.append("   结算时才会揭晓——若二次爆牌将扣双倍筹码！")
                    log_visible = True; log_scroll = 0
                elif msg.startswith("[ACH]"):
                    ach_key = msg.replace("[ACH]","").strip()
                    new_achievements.append(ach_key)
                    ach_popup_tick = anim_tick
                elif msg.startswith("[GAMESTART]"):
                    in_lobby=False; screen_state="prep"; game_started=True
                    hand=[]; waiting_for=""; available_opts=[]; is_banker=False
                    item_used={}; peek_result=""; is_blinded=False; log_scroll=0
                    dealer_peek_hand=[]; paradox_ready=False; paradox_active=False
                    game_phase="player_turn"; screen_shop=False; show_item_panel=False
                    bet_mode=False; bet_submitted=False
                    active_used_count=0; passive_used_count=0
                    # 重置商店刷新标志，新局打开商店会重新生成道具池
                    shop_opened_gid=-99
                    silence_field=False; doom_beacon_set=False
                    blood_moon_active=False; tornado_active=False
                    can_side_bet=False; side_bet_mode=False
                    duel_active=False; duel_result=""
                    dealer_visible=[]; dealer_upcard_str=""
                    prep_active=""; prep_passive=""; prep_confirmed=False
                    # 同步服务器局ID
                    try:
                        _gid = int(msg.replace("[GAMESTART]","").strip())
                        current_game_id = _gid
                    except:
                        current_game_id += 1
                    # 每局重置卡背映射
                    CARD_BACK_MAP = _build_card_back_map()
                    # 每局重置盲盒限购
                    try:
                        _bc = getattr(Shop,"_box_buy_count",None)
                        if _bc is not None: _bc.clear()
                    except: pass
                    # tick冷却（每局-1）
                    try: getattr(Shop,"tick_cooldowns",lambda a:None)(my_name)
                    except: pass
                    # 检查盲盒道具过期
                    try:
                        _exp = getattr(Shop,"expire_box_items",lambda a,b:[])(my_name, current_game_id)
                        for _ei in _exp: log.append(f"⏰ 【{_ei}】已过期失效")
                    except: pass
                    # 超好运buff
                    if lucky_buff_active:
                        lucky_buff_games -= 1
                        if lucky_buff_games <= 0:
                            lucky_buff_active = False; log.append("⭐ 超好运buff已结束")
                        else:
                            log.append(f"⭐ 超好运buff剩余{lucky_buff_games}局")
                    # 日志保留上一局
                    sep = "━━━━ 新一局 ━━━━"
                    sep_indices = [i for i,l in enumerate(log) if sep in l]
                    if len(sep_indices) >= 1:
                        log[:] = log[sep_indices[-1]:]
                    elif len(log) > 30:
                        log[:] = log[-30:]
                elif msg.startswith("[RESULT]"):
                    parts=msg.replace("[RESULT]","").split("|")
                    result_gain=int(parts[0]); money=int(parts[1])
                    result=parts[2] if len(parts)>2 else ""
                    save_record(my_name, money)
                    play_bgm("result")
                    if result_gain>0: add_particles(WIDTH//2,HEIGHT//2,C_GOLD2,20)
                elif msg == "[SILENCE]":
                    silence_field = True
                    log.append("🤫 沉默干扰器！本局所有主动道具被禁用！")
                elif msg == "[DOOM_BEACON]":
                    doom_beacon_set = True
                    log.append("🧨 厄运信标已埋下！下一个要牌的人必抽10点牌！")
                elif msg == "[DOOM_TRIGGERED]":
                    doom_beacon_set = False
                    log.append("🧨 厄运信标引爆！")
                elif msg.startswith("[STEAL_ITEM]"):
                    stolen = msg.replace("[STEAL_ITEM]","").strip()
                    if stolen in my_items:
                        my_items[stolen] = max(0,my_items.get(stolen,0)-1)
                        if my_items[stolen]==0: del my_items[stolen]
                    log.append(f"🧤 第三只手：你的【{stolen}】被偷走了！")
                elif msg.startswith("[STEAL_CHIPS]"):
                    amt = int(msg.replace("[STEAL_CHIPS]","").strip())
                    money = max(0, money - amt)
                    log.append(f"🧤 第三只手：被偷走 {fmt_chips(amt)} 筹码！")
                elif msg.startswith("[VAMPIRE]"):
                    amt = int(msg.replace("[VAMPIRE]","").strip())
                    money = max(0, money - amt)
                    log.append(f"🧛 吸血印记触发！被抽走 {fmt_chips(amt)} 筹码！")
                    add_particles(WIDTH//2, HEIGHT//2, (150,0,100), 15)
                elif msg.startswith("[VAMPIRE_GAIN]"):
                    amt = int(msg.replace("[VAMPIRE_GAIN]","").strip())
                    money += amt
                    log.append(f"🧛 吸血印记：获得 {fmt_chips(amt)} 筹码！")
                elif msg == "[BLOOD_MOON]":
                    blood_moon_active = True
                    log.append("🩸 血月之夜！无点数上限，但抽到黑桃直接爆牌！")
                elif msg == "[TORNADO]":
                    tornado_active = True
                    log.append("🌪️ 龙卷风！手牌将顺时针平移！")
                elif msg.startswith("[SIDE_BET_OK]"):
                    log.append(f"🎲 外围下注成功：{msg.replace('[SIDE_BET_OK]','')}")
                elif msg.startswith("[SIDE_BET_RESULT]"):
                    parts = msg.replace("[SIDE_BET_RESULT]","").split("|")
                    if len(parts)==2:
                        gain2 = int(parts[0]); money += gain2
                        log.append(f"🎲 外围结算：{parts[1]} ({'+' if gain2>=0 else ''}{fmt_chips(gain2)})")
                        if gain2 > 0: add_particles(WIDTH//2,HEIGHT//2,C_GOLD2,20)
                elif msg == "[CAN_SIDE_BET]":
                    can_side_bet = True
                    log.append("🎲 你可以对其他玩家进行外围下注！点击道具面板使用")
                elif msg.startswith("[DUEL_START]"):
                    duel_active = True; duel_countdown = 90  # 1.5秒@60fps
                    log.append("⚔️ 西部决斗触发！平局摊牌！")
                elif msg.startswith("[DUEL_CARD]"):
                    parts2 = msg.replace("[DUEL_CARD]","").split("|")
                    if len(parts2)==2:
                        duel_my_card=parts2[0]; duel_opp_card=parts2[1]
                elif msg.startswith("[DUEL_RESULT]"):
                    duel_result = msg.replace("[DUEL_RESULT]","").strip()
                    duel_active = False
                    log.append(f"⚔️ 决斗结果：{duel_result}")
                elif msg.startswith("[BLINDBOX_RESULT]"):
                    _br = msg.replace("[BLINDBOX_RESULT]","").strip()
                    _handle_blindbox_result(_br, my_name)
                    log_visible = True; log_scroll = 0
                elif msg == "[PREP_START]":
                    screen_state="prep"
                    prep_active=""; prep_passive=""; prep_confirmed=False
                    prep_start_time=anim_tick  # 记录开始时间用于倒计时
                elif msg.startswith("[SCALE_WIN]"):
                    log.append("⚖️ 天平倾斜！平局判你赢！")
                elif msg.startswith("[DEALER_UPCARD]"):
                    # 服务器发送庄家明牌
                    dealer_upcard_str = msg.replace("[DEALER_UPCARD]","").strip()
                    dealer_visible = [dealer_upcard_str]
                else:
                    info_text = msg.replace("[INFO]","")
                    log.append(info_text)
                    # 从日志解析庄家明牌（兼容旧协议）
                    if "庄家明牌:" in info_text:
                        _dc = info_text.split("庄家明牌:")[-1].strip()
                        if _dc and len(_dc) <= 5:
                            dealer_upcard_str = _dc
                            dealer_visible = [_dc]
                    # 庄家翻牌
                    elif "庄家翻开暗牌:" in info_text:
                        _dc2 = info_text.split("庄家翻开暗牌:")[-1].strip()
                        if _dc2 and len(_dc2) <= 5:
                            dealer_visible = [_dc2] + dealer_visible
                    elif "庄家摸牌:" in info_text:
                        _dc3 = info_text.split("庄家摸牌:")[-1].split("，")[0].strip()
                        if _dc3 and len(_dc3) <= 5 and _dc3 not in dealer_visible:
                            dealer_visible.append(_dc3)
                    if len(log)>50: log.pop(0)
        except Exception as _recv_ex:
            import traceback
            print(f"[receive线程崩溃] {_recv_ex}")
            traceback.print_exc()
            break

def _load_player_cosmetics(name):
    global my_items, my_card_back, my_tablecloth
    global my_owned_backs, my_owned_cloths, my_achievements, my_title
    global CARD_BACK_MAP
    try:
        pd = Shop.get_player_data(name)
        my_items        = pd.get("items", {})
        my_card_back    = pd.get("card_back", "")
        my_tablecloth   = pd.get("tablecloth", "default")
        my_owned_backs  = pd.get("owned_backs", [])
        my_owned_cloths = pd.get("owned_cloths", ["default"])
        my_achievements = pd.get("achievements", [])
        my_title        = pd.get("title", "")
        pass  # 卡背映射在每局开始时生成
    except:
        pass

def _load_player_cosmetics_custom(name):
    """加载自定义模式独立存档"""
    global my_items, my_card_back, my_tablecloth
    global my_owned_backs, my_owned_cloths, my_achievements, my_title
    try:
        pd = Shop.get_player_data("__custom__" + name)
        my_items        = pd.get("items", {})
        my_card_back    = pd.get("card_back", "")
        my_tablecloth   = pd.get("tablecloth", "default")
        my_owned_backs  = pd.get("owned_backs", [])
        my_owned_cloths = pd.get("owned_cloths", ["default"])
        my_achievements = pd.get("achievements", [])
        my_title        = pd.get("title", "")
    except:
        pass

def get_custom_chips(name):
    """自定义模式每次给50000筹码（独立存档）"""
    import datetime
    data = load_save()
    key  = "__custom__" + name
    players = data.get("players", {})
    today   = datetime.date.today().isoformat()
    logins  = data.get("daily_logins", {})
    chips   = players.get(key, 0)
    if logins.get(key) != today:
        chips += 5000
        logins[key] = today
        data["daily_logins"] = logins
        if "players" not in data: data["players"] = {}
        data["players"][key] = chips
        save_full(data)
    return max(chips, 5000)

def save_record_solo(name, chips):
    """单人模式存档，根据子模式决定存到哪里"""
    if solo_submode == "custom":
        save_record("__custom__" + name, chips)
    else:
        save_record(name, chips)  # normal 模式共享存档

def get_solo_relief(name):
    """人机模式救济金：低于100时可领，每日5次，每次10000"""
    import datetime
    data  = load_save()
    today = datetime.date.today().isoformat()
    key   = f"solo_relief_{name}"
    rec   = data.get(key, {"date":"","count":0})
    if rec["date"] != today:
        rec = {"date": today, "count": 0}
    if rec["count"] >= SOLO_RELIEF_MAX_DAILY:
        return 0, f"今日救济金已领完（{SOLO_RELIEF_MAX_DAILY}次/日）"
    rec["count"] += 1
    data[key] = rec
    save_full(data)
    return SOLO_RELIEF_AMOUNT, f"领取救济金 {SOLO_RELIEF_AMOUNT}，今日剩余 {SOLO_RELIEF_MAX_DAILY - rec['count']} 次"

def get_solo_relief_count(name):
    """获取今日剩余救济次数"""
    import datetime
    data  = load_save()
    today = datetime.date.today().isoformat()
    key   = f"solo_relief_{name}"
    rec   = data.get(key, {"date":"","count":0})
    if rec["date"] != today:
        return SOLO_RELIEF_MAX_DAILY
    return max(0, SOLO_RELIEF_MAX_DAILY - rec["count"])

# 客户端阶段限制（与服务器保持一致）
_CLIENT_PHASE_RULES = {
    "搏命契约": ["betting"],          # 只在下注阶段用
    "灵魂链接": ["betting"],          # 只在下注阶段用
    "透视眼镜": ["player_turn"],      # 你的回合
    "再来一次": ["player_turn"],      # 你的回合
    "强买强卖": ["other_turn"],       # 他人回合（不能在自己回合用）
    "致盲烟雾": ["other_turn"],       # 他人回合
    "移花接木": ["player_turn"],      # 你的回合
    "命运盲盒": ["player_turn","betting"],  # 你的回合或下注阶段都可开
}

def _item_phase_ok(iname):
    """检查当前阶段是否允许使用该道具"""
    from items import PASSIVE_ITEMS as _PI
    if iname in _PI: return True  # 被动道具面板只显示状态
    allowed = _CLIENT_PHASE_RULES.get(iname, ["player_turn"])
    return game_phase in allowed

def _shop_name():
    """返回当前模式下商店应使用的存档名"""
    if solo_submode == "custom" and screen_state == "solo":
        return "__custom__" + my_name
    return my_name

def _shop_game_id():
    """商店所对应的局号：多人prep/game都使用当前局；单人result预览下一局。"""
    if screen_state == "solo" and solo_state == "result":
        return current_game_id + 1
    return current_game_id

def _clear_shop_cache():
    """每局开始时清除道具池缓存"""
    try:
        _sn = _solo_shop_name() if screen_state=="solo" else my_name
        _bc = getattr(Shop,"_pshop_cache",{})
        for _k in [k for k in list(_bc.keys()) if k.startswith(_sn+"_")]:
            del _bc[_k]
    except: pass

def _reload_cosmetics():
    """根据当前模式重新加载外观数据"""
    global CARD_BACK_MAP
    if solo_submode == "custom" and screen_state == "solo":
        _load_player_cosmetics_custom(my_name)
    else:
        _load_player_cosmetics(my_name)
    CARD_BACK_MAP = _build_card_back_map()  # 购买后立即更新

connect_status   = ""  # "" | "connecting" | "ok" | "fail:<msg>"
connect_fail_tick = 0  # 失败时记录anim_tick，显示3秒

def do_connect(name, ip):
    """在子线程里连接，不阻塞主线程"""
    global connect_status
    connect_status = "connecting"
    def _worker():
        global my_name, server_ip, money, screen_state, client, connected, connect_status
        try:
            try: client.close()
            except: pass
            import socket as _socket
            _new_sock = _socket.socket()
            _new_sock.settimeout(8)
            my_name   = name
            server_ip = ip
            starting  = get_starting_chips(name)
            _new_sock.connect((ip, 5555))
            msg = _new_sock.recv(1024).decode()
            if msg.startswith("[NAME]"):
                _new_sock.send(f"{name}|{starting}\n".encode())
            _new_sock.settimeout(None)
            client = _new_sock  # 连接成功后才赋值给全局
            money = starting
            save_profile(name, ip)
            _load_player_cosmetics(name)
            screen_state = "lobby"
            connected = True
            connect_status = "ok"
            threading.Thread(target=receive, daemon=True).start()
        except Exception as ex:
            connected = False
            connect_status = f"fail:{ex}"
    threading.Thread(target=_worker, daemon=True).start()

# ===== 绘制工具 =====
def draw_rect_alpha(surface, color, rect, alpha=180, radius=0):
    s=pygame.Surface((rect[2],rect[3]),pygame.SRCALPHA)
    pygame.draw.rect(s,(*color[:3],alpha),(0,0,rect[2],rect[3]),border_radius=radius)
    surface.blit(s,(rect[0],rect[1]))

def draw_text_shadow(surf, text, font, color, x, y, offset=2):
    surf.blit(font.render(text,True,(0,0,0)),(x+offset,y+offset))
    surf.blit(font.render(text,True,color),(x,y))

def draw_button(rect, label, color, hover=False, disabled=False):
    x,y,w,h=rect
    base=C_DARKGRAY if disabled else (tuple(min(255,c+30) for c in color) if hover else color)
    pygame.draw.rect(screen,(0,0,0),pygame.Rect(x+3,y+3,w,h),border_radius=10)
    pygame.draw.rect(screen,base,rect,border_radius=10)
    draw_rect_alpha(screen,(255,255,255),(x+2,y+2,w-4,h//3),40,8)
    pygame.draw.rect(screen,C_GOLD if not disabled else C_DARKGRAY,rect,2,border_radius=10)
    txt=font_md.render(label,True,C_WHITE if not disabled else C_GRAY)
    screen.blit(txt,(x+(w-txt.get_width())//2,y+(h-txt.get_height())//2))

def draw_input_box(rect, value, focused, placeholder="", font=None):
    """通用输入框"""
    if font is None: font = font_lg
    x,y,w,h = rect
    border = C_GOLD2 if focused else C_GOLD
    pygame.draw.rect(screen,(20,50,30),rect,border_radius=8)
    pygame.draw.rect(screen,border,rect,2,border_radius=8)
    cursor = "|" if focused and anim_tick%60<30 else ""
    disp   = value if value else placeholder
    dc     = C_WHITE if value else C_GRAY
    screen.blit(font.render(disp+cursor,True,dc),(x+12,y+(h-font.get_height())//2))

def draw_card(x, y, card_str, w=CARD_W, h=CARD_H, show_back=False, back_name=""):
    """
    show_back=True 时显示卡背（用于盲牌模式或他人暗牌）
    back_name: 指定卡背皮肤名
    """
    cx, cy = x + w//2, y + h//2
    if show_back:
        # 显示卡背图片或默认卡背
        back_img_name = back_name or my_card_back
        back_path = os.path.join(BASE_DIR,"Card Back Visual", back_img_name+".png") if back_img_name else ""
        drawn = False
        if back_img_name and os.path.exists(back_path):
            try:
                cache_key = f"{back_img_name}_{w}_{h}"
                if cache_key not in card_back_cache:
                    raw = pygame.image.load(back_path).convert_alpha()
                    card_back_cache[cache_key] = pygame.transform.smoothscale(raw,(w,h))
                img = card_back_cache[cache_key]
                pygame.draw.rect(screen,(0,0,0),(x+4,y+4,w,h),border_radius=8)
                screen.blit(img,(x,y))
                pygame.draw.rect(screen,C_GOLD,(x,y,w,h),1,border_radius=8)
                drawn = True
            except: pass
        if not drawn:
            pygame.draw.rect(screen,(0,0,0),(x+4,y+4,w,h),border_radius=8)
            pygame.draw.rect(screen,(30,60,120),(x,y,w,h),border_radius=8)
            pygame.draw.rect(screen,C_GOLD,(x,y,w,h),1,border_radius=8)
        # 绘制卡背特效
        if back_img_name and back_img_name in CARD_BACKS:
            effect = CARD_BACKS[back_img_name]["effect"]
            draw_card_effect(screen, effect, cx, cy, anim_tick)
        return

    img=card_images.get(card_str)
    if img:
        if w!=CARD_W or h!=CARD_H:
            img=pygame.transform.smoothscale(img,(w,h))
        pygame.draw.rect(screen,(0,0,0),(x+4,y+4,w,h),border_radius=8)
        screen.blit(img,(x,y))
        pygame.draw.rect(screen,C_GOLD,(x,y,w,h),1,border_radius=8)
    else:
        pygame.draw.rect(screen,(0,0,0),(x+4,y+4,w,h),border_radius=10)
        pygame.draw.rect(screen,C_WHITE,(x,y,w,h),border_radius=10)
        suit=card_str[0]; rank=card_str[1:]
        color=(200,30,30) if suit in['♥','♦'] else (20,20,20)
        screen.blit(font_sm.render(rank,True,color),(x+5,y+4))
        screen.blit(font_sm.render(suit,True,color),(x+5,y+20))
        big=font_lg.render(suit,True,color)
        screen.blit(big,(x+(w-big.get_width())//2,y+(h-big.get_height())//2))

# ===== 旋涡翻牌动画系统 =====
def queue_card_reveal(card_str, x, y, w=CARD_W, h=CARD_H):
    """把一张牌加入翻牌动画队列"""
    back_name = CARD_BACK_MAP.get(card_str, "")
    card_reveal_queue.append({
        "card": card_str, "x": x, "y": y, "w": w, "h": h,
        "back": back_name, "tick": 0,
        "phase": "vortex",   # vortex(0-25) -> backshow(25-38) -> flip(38-55)
        "done": False,
    })

def draw_card_reveal_animations():
    """每帧调用，绘制所有正在播放的翻牌动画，返回还有多少个未完成"""
    still_playing = []
    for anim in card_reveal_queue:
        t   = anim["tick"]
        x,y = anim["x"], anim["y"]
        w,h = anim["w"], anim["h"]
        cx,cy = x+w//2, y+h//2
        back  = anim["back"]

        if t < 25:
            # === 旋涡粒子阶段 ===
            anim["phase"] = "vortex"
            progress = t / 25.0
            # 遮盖背景（半透明黑色渐入）
            draw_rect_alpha(screen, (0,0,0), (x-10,y-10,w+20,h+20), int(180*progress), 8)
            # 旋涡粒子：从外向内螺旋聚集
            num_particles = 32
            import math as _m
            back_color = (200,180,100)
            if back in CARD_BACKS:
                back_color = CARD_BACKS[back].get("color", (200,180,100))
            for pi in range(num_particles):
                angle_base = 2*_m.pi*pi/num_particles
                # 粒子从外围螺旋收缩
                radius = (1.0 - progress) * 80 + 5
                angle  = angle_base + progress * _m.pi * 4  # 旋转2圈
                px2 = cx + _m.cos(angle) * radius
                py2 = cy + _m.sin(angle) * radius
                size = max(1, int(4 * progress + 1))
                alpha_p = int(255 * min(1.0, progress * 2))
                col = tuple(min(255, int(c * (0.5 + 0.5*progress))) for c in back_color[:3])
                pygame.draw.circle(screen, col, (int(px2), int(py2)), size)
            # 中心光点闪烁
            glow_r = int(15 * progress)
            if glow_r > 0:
                draw_rect_alpha(screen, back_color,
                    (cx-glow_r, cy-glow_r, glow_r*2, glow_r*2), 120, glow_r)

        elif t < 38:
            # === 卡背显示阶段（卡牌从旋涡中升起）===
            anim["phase"] = "backshow"
            prog2 = (t - 25) / 13.0
            # 卡牌从小到大缩放出现
            scale = 0.3 + 0.7 * prog2
            sw, sh = int(w*scale), int(h*scale)
            sx2 = cx - sw//2; sy2 = cy - sh//2
            # 绘制卡背
            back_color2 = CARD_BACKS.get(back, {}).get("color", (60,60,120))
            draw_rect_alpha(screen, (0,0,0), (sx2+3,sy2+3,sw,sh), 180, 6)
            draw_rect_alpha(screen, back_color2, (sx2,sy2,sw,sh), 220, 6)
            pygame.draw.rect(screen, C_GOLD, (sx2,sy2,sw,sh), 1, border_radius=6)
            # 加载卡背图片
            cache_key = f"{back}_{sw}_{sh}"
            if back and cache_key not in card_back_cache:
                import os as _os
                bp = _os.path.join(BASE_DIR,"Card Back Visual",back+".png")
                if _os.path.exists(bp):
                    try:
                        raw = pygame.image.load(bp).convert_alpha()
                        card_back_cache[cache_key] = pygame.transform.smoothscale(raw,(sw,sh))
                    except: pass
            if cache_key in card_back_cache:
                screen.blit(card_back_cache[cache_key], (sx2,sy2))
            # 粒子特效
            if back in CARD_BACKS:
                effect = CARD_BACKS[back]["effect"]
                draw_card_effect(screen, effect, cx, cy, t*3)
            # 旋涡残留粒子消散
            import math as _m
            back_color3 = CARD_BACKS.get(back,{}).get("color",(200,180,100))
            for pi in range(16):
                angle = 2*_m.pi*pi/16 + prog2*_m.pi
                radius = (1.0-prog2) * 30
                px3 = cx + _m.cos(angle)*radius
                py3 = cy + _m.sin(angle)*radius
                col3 = tuple(min(255,c) for c in back_color3[:3])
                pygame.draw.circle(screen, col3, (int(px3),int(py3)), max(1,int(3*(1-prog2))))

        elif t < 55:
            # === 翻牌阶段（卡背翻转变成正面）===
            anim["phase"] = "flip"
            prog3 = (t - 38) / 17.0
            # 模拟翻转：X方向先压缩到0再展开
            if prog3 < 0.5:
                # 前半：卡背压缩消失
                scale_x = 1.0 - prog3*2
                sw2 = max(1, int(w * scale_x)); sh2 = h
                sx3 = cx - sw2//2; sy3 = y
                back_color4 = CARD_BACKS.get(back,{}).get("color",(60,60,120))
                draw_rect_alpha(screen,(0,0,0),(sx3+2,sy3+2,sw2,sh2),180,4)
                draw_rect_alpha(screen,back_color4,(sx3,sy3,sw2,sh2),220,4)
                pygame.draw.rect(screen,C_GOLD,(sx3,sy3,sw2,sh2),1,border_radius=4)
                ck2 = f"{back}_{sw2}_{sh2}"
                if back and ck2 not in card_back_cache:
                    import os as _os
                    bp = _os.path.join(BASE_DIR,"Card Back Visual",back+".png")
                    if _os.path.exists(bp):
                        try:
                            raw=pygame.image.load(bp).convert_alpha()
                            card_back_cache[ck2]=pygame.transform.smoothscale(raw,(sw2,sh2))
                        except: pass
                if ck2 in card_back_cache:
                    screen.blit(card_back_cache[ck2],(sx3,sy3))
            else:
                # 后半：正面展开
                scale_x2 = (prog3 - 0.5) * 2
                sw3 = max(1, int(w * scale_x2)); sh3 = h
                sx4 = cx - sw3//2; sy4 = y
                draw_rect_alpha(screen,(0,0,0),(sx4+2,sy4+2,sw3,sh3),180,4)
                # 绘制牌面
                img = card_images.get(anim["card"])
                if img and sw3 > 4:
                    scaled = pygame.transform.smoothscale(img,(sw3,sh3))
                    screen.blit(scaled,(sx4,sy4))
                else:
                    pygame.draw.rect(screen,C_WHITE,(sx4,sy4,sw3,sh3),border_radius=4)
                pygame.draw.rect(screen,C_GOLD,(sx4,sy4,sw3,sh3),1,border_radius=4)
        else:
            # 动画完成，绘制最终正面
            draw_card(x, y, anim["card"], w, h)
            anim["done"] = True

        anim["tick"] += 1
        if not anim["done"]:
            still_playing.append(anim)

    # 清理已完成的动画
    card_reveal_queue[:] = [a for a in card_reveal_queue if not a["done"]]
    return len(card_reveal_queue)

def is_card_animating():
    """是否有翻牌动画正在播放"""
    return len(card_reveal_queue) > 0

def background():
    pass  # placeholder for spacing

def draw_volume_btn(y_offset=78):
    """所有界面通用音量按钮，右上角"""
    mx,my_p = pygame.mouse.get_pos()
    try:
        vol = pygame.mixer.music.get_volume()
        vol_pct = int(vol * 100)
    except:
        vol_pct = 0
    vol_label = f"🔊 {vol_pct}%"
    vol_rect = pygame.Rect(WIDTH-115, y_offset, 104, 28)
    draw_rect_alpha(screen, C_PANEL, (vol_rect.x,vol_rect.y,vol_rect.w,vol_rect.h), 200, 6)
    pygame.draw.rect(screen, C_GOLD, vol_rect, 1, border_radius=6)
    vt = font_sm.render(vol_label, True, C_GOLD)
    screen.blit(vt, (vol_rect.x+6, vol_rect.y+6))
    return vol_rect

def draw_background():
    if bg_image:
        screen.blit(bg_image,(0,0))
        s=pygame.Surface((WIDTH,HEIGHT),pygame.SRCALPHA)
        pygame.draw.ellipse(s,(0,60,20,120),(50,90,WIDTH-100,HEIGHT-150))
        screen.blit(s,(0,0))
        pygame.draw.ellipse(screen,C_GOLD,(50,90,WIDTH-100,HEIGHT-150),3)
    else:
        screen.fill(C_BG)
        s=pygame.Surface((WIDTH,HEIGHT),pygame.SRCALPHA)
        tc = TABLECLOTHS.get(my_tablecloth, TABLECLOTHS["default"])["color"]
        felt = tuple(max(0,c-20) for c in tc)
        pygame.draw.ellipse(s,(*felt,80),(50,90,WIDTH-100,HEIGHT-150))
        screen.blit(s,(0,0))
        pygame.draw.ellipse(screen,tc,(50,90,WIDTH-100,HEIGHT-150))
        pygame.draw.ellipse(screen,C_GOLD,(50,90,WIDTH-100,HEIGHT-150),3)
    for i in range(8):
        angle=math.pi*2/8*i+anim_tick*0.003
        cx,cy=WIDTH//2,HEIGHT//2; r=260
        pygame.draw.line(screen,C_GOLD,
            (int(cx+math.cos(angle)*(r-20)),int(cy+math.sin(angle)*(r-20))),
            (int(cx+math.cos(angle)*r),int(cy+math.sin(angle)*r)),1)

# ===== 名称输入界面 =====
def draw_name_input():
    draw_background()
    t="♠ BLACK JACK ♠"
    draw_text_shadow(screen,t,font_xl,C_GOLD,WIDTH//2-font_xl.size(t)[0]//2,50)

    # 面板
    pw,ph=540,380
    px,py=WIDTH//2-pw//2,130
    draw_rect_alpha(screen,C_PANEL,(px,py,pw,ph),215,16)
    pygame.draw.rect(screen,C_GOLD,(px,py,pw,ph),2,border_radius=16)

    # 历史存档
    save_data=load_save()
    players=save_data.get("players",{})
    h2=font_md.render("📁 历史存档",True,C_GOLD)
    screen.blit(h2,(WIDTH//2-h2.get_width()//2,py+14))
    pygame.draw.line(screen,C_GOLD,(px+20,py+42),(px+pw-20,py+42),1)

    if players:
        y2=py+50
        for name,chips in list(players.items())[:4]:
            rc=C_GREEN2 if chips>1500 else (C_RED2 if chips<500 else C_WHITE)
            row=font_sm.render(f"  {name}   筹码: {chips}",True,rc)
            screen.blit(row,(WIDTH//2-row.get_width()//2,y2)); y2+=23
    else:
        ns=font_sm.render("暂无存档，新玩家起始 1500 筹码",True,C_GRAY)
        screen.blit(ns,(WIDTH//2-ns.get_width()//2,py+55))

    # 名字输入
    nl=font_md.render("玩家名字",True,C_WHITE)
    screen.blit(nl,(px+30,py+160))
    name_rect=pygame.Rect(px+30,py+186,pw-60,44)
    draw_input_box(name_rect,fi_name,fi_focus=="name","请输入名字（最多12字）")

    # IP输入
    il=font_md.render("服务器 IP 地址",True,C_WHITE)
    screen.blit(il,(px+30,py+244))
    ip_rect=pygame.Rect(px+30,py+270,pw-60,44)
    draw_input_box(ip_rect,fi_ip,fi_focus=="ip","例：192.168.0.101  本机填 127.0.0.1")

    # 提示
    if fi_name.strip() and fi_name in players:
        c2=players[fi_name]
        tip=font_sm.render(f"欢迎回来！当前筹码: {c2}",True,C_CYAN)
        screen.blit(tip,(WIDTH//2-tip.get_width()//2,py+325))
    elif fi_name.strip():
        tip=font_sm.render(f"新玩家，起始 {BONUS_PER_SESSION} 筹码",True,C_GRAY)
        screen.blit(tip,(WIDTH//2-tip.get_width()//2,py+325))

    # 确认按钮
    ok_disabled = not (fi_name.strip() and fi_ip.strip())
    ok_btn=pygame.Rect(WIDTH//2-110,py+350,220,52)
    mx,my_p=pygame.mouse.get_pos()
    draw_button(ok_btn,"进入游戏 ▶",C_READY,ok_btn.collidepoint(mx,my_p) and not ok_disabled,ok_disabled)

    return ok_btn, name_rect, ip_rect

# ===== 修改信息弹窗（大厅右下角触发）=====
def draw_edit_popup():
    """返回 (ok_btn, cancel_btn, name_rect, ip_rect)"""
    pw,ph=460,260
    px,py=WIDTH//2-pw//2,HEIGHT//2-ph//2
    # 遮罩
    draw_rect_alpha(screen,(0,0,0),(0,0,WIDTH,HEIGHT),140)
    draw_rect_alpha(screen,C_PANEL,(px,py,pw,ph),240,14)
    pygame.draw.rect(screen,C_GOLD,(px,py,pw,ph),2,border_radius=14)

    title=font_lg.render("✏ 修改信息",True,C_GOLD)
    screen.blit(title,(WIDTH//2-title.get_width()//2,py+14))
    pygame.draw.line(screen,C_GOLD,(px+20,py+48),(px+pw-20,py+48),1)

    # 名字框
    nl=font_md.render("名字",True,C_WHITE)
    screen.blit(nl,(px+30,py+60))
    name_rect=pygame.Rect(px+30,py+84,pw-60,42)
    draw_input_box(name_rect,edit_name,edit_focus=="name","")

    # IP框
    il=font_md.render("服务器 IP",True,C_WHITE)
    screen.blit(il,(px+30,py+138))
    ip_rect=pygame.Rect(px+30,py+162,pw-60,42)
    draw_input_box(ip_rect,edit_ip,edit_focus=="ip","")

    mx,my_p=pygame.mouse.get_pos()
    ok_btn=pygame.Rect(px+pw//2-120,py+218,110,36)
    ca_btn=pygame.Rect(px+pw//2+10, py+218,110,36)
    draw_button(ok_btn,"✔ 确认",C_READY,ok_btn.collidepoint(mx,my_p))
    draw_button(ca_btn,"✘ 取消",C_UNREADY,ca_btn.collidepoint(mx,my_p))
    return ok_btn,ca_btn,name_rect,ip_rect




# ===== 观战界面 =====
def draw_spectating():
    draw_background()

    # 顶部栏
    draw_rect_alpha(screen, C_PANEL, (0,0,WIDTH,70), 200)
    pygame.draw.line(screen, C_GOLD, (0,70), (WIDTH,70), 2)
    draw_text_shadow(screen, "👁 观战模式", font_lg, C_CYAN, 20, 18)
    draw_text_shadow(screen, my_name, font_md, C_GRAY, 220, 22)
    draw_text_shadow(screen, f"筹码: {money}", font_md, C_GOLD2, WIDTH-220, 22)

    # 观战提示横幅
    banner = font_lg.render("游戏进行中，本局结束后自动加入", True, C_YELLOW)
    bx = WIDTH//2 - banner.get_width()//2
    draw_rect_alpha(screen, (0,0,0), (bx-15, 88, banner.get_width()+30, 44), 160, 8)
    screen.blit(banner, (bx, 95))

    # 日志面板（居中大显示）
    LOG_X, LOG_Y, LOG_W, LOG_H = WIDTH//2-340, 145, 680, 480
    draw_rect_alpha(screen, C_PANEL, (LOG_X,LOG_Y,LOG_W,LOG_H), 200, 12)
    pygame.draw.rect(screen, C_CYAN, (LOG_X,LOG_Y,LOG_W,LOG_H), 1, border_radius=12)
    hdr = font_md.render("📋 实时牌局", True, C_CYAN)
    screen.blit(hdr, (LOG_X+12, LOG_Y+10))
    pygame.draw.line(screen, C_CYAN, (LOG_X+8,LOG_Y+36), (LOG_X+LOG_W-8,LOG_Y+36), 1)

    line_h = 22
    max_lines = (LOG_H - 50) // line_h
    ly = LOG_Y + 42
    clip2 = pygame.Rect(LOG_X+2, LOG_Y+40, LOG_W-4, LOG_H-42)
    oc2 = screen.get_clip(); screen.set_clip(clip2)
    for msg in log[-max_lines:]:
        if "赢" in msg or "✅" in msg:    c = C_GREEN2
        elif "爆" in msg or "输" in msg: c = C_RED2
        elif "轮到" in msg:              c = C_YELLOW
        elif "BJ" in msg or "Black" in msg: c = C_GOLD2
        elif "庄家" in msg:              c = C_CYAN
        else:                           c = (200,200,200)
        screen.blit(font_sm.render(msg, True, c), (LOG_X+10, ly))
        ly += line_h
    screen.set_clip(oc2)

    # 底部等待提示（脉冲动画）
    pulse = int(160 + 95*math.sin(anim_tick*0.04))
    wt = font_md.render("⏳ 等待本局结束，即将加入下一局...", True, (pulse, pulse, 80))
    screen.blit(wt, (WIDTH//2-wt.get_width()//2, HEIGHT-45))

# ===== 保险界面 =====
def draw_insurance():
    draw_background()
    t = "🛡 保险阶段"
    draw_text_shadow(screen,t,font_xl,C_GOLD,WIDTH//2-font_xl.size(t)[0]//2,50)

    draw_rect_alpha(screen,C_PANEL,(WIDTH//2-240,130,480,300),210,16)
    pygame.draw.rect(screen,C_GOLD,(WIDTH//2-240,130,480,300),2,border_radius=16)

    desc1=font_md.render("庄家明牌为A，是否购买保险？",True,C_WHITE)
    screen.blit(desc1,(WIDTH//2-desc1.get_width()//2,155))
    desc2=font_sm.render("保险金 = 赌注的一半，若庄家有BJ则获得2倍保险金",True,C_GRAY)
    screen.blit(desc2,(WIDTH//2-desc2.get_width()//2,188))

    if insurance_done:
        st=font_lg.render("✅ 已选择，等待结果...",True,C_GREEN2)
        screen.blit(st,(WIDTH//2-st.get_width()//2,250))
    else:
        mx,my_p=pygame.mouse.get_pos()
        buy_btn=pygame.Rect(WIDTH//2-160,230,140,55)
        no_btn =pygame.Rect(WIDTH//2+20, 230,140,55)
        draw_button(buy_btn,"🛡 购买保险",C_RED,    buy_btn.collidepoint(mx,my_p))
        draw_button(no_btn, "❌ 不买",    C_TABLE2, no_btn.collidepoint(mx,my_p))
        return buy_btn, no_btn
    return None, None

# ===== 抢庄界面 =====
def draw_grabbing():
    draw_background()
    t = "♠ 抢庄阶段 ♠"
    draw_text_shadow(screen, t, font_xl, C_GOLD, WIDTH//2-font_xl.size(t)[0]//2, 50)

    draw_rect_alpha(screen, C_PANEL, (WIDTH//2-220, 130, 440, 320), 210, 16)
    pygame.draw.rect(screen, C_GOLD, (WIDTH//2-220, 130, 440, 320), 2, border_radius=16)

    desc = font_md.render("是否抢庄？庄家赢闲家的赌注，输则赔付", True, C_GRAY)
    screen.blit(desc, (WIDTH//2-desc.get_width()//2, 155))

    if grabbing_done:
        status = font_lg.render("✅ 已提交，等待其他玩家...", True, C_GREEN2)
        screen.blit(status, (WIDTH//2-status.get_width()//2, 230))
    else:
        mx, my_p = pygame.mouse.get_pos()
        grab_btn   = pygame.Rect(WIDTH//2-160, 210, 140, 58)
        nograb_btn = pygame.Rect(WIDTH//2+20,  210, 140, 58)
        draw_button(grab_btn,   "🎰 抢庄", C_RED,    grab_btn.collidepoint(mx, my_p))
        draw_button(nograb_btn, "🙅 不抢", C_TABLE2, nograb_btn.collidepoint(mx, my_p))

    if banker_name:
        bc = C_GOLD2 if banker_name == my_name else C_CYAN
        bt = font_lg.render(f"庄家: {banker_name}", True, bc)
        screen.blit(bt, (WIDTH//2-bt.get_width()//2, 300))

    for i, msg in enumerate(log[-4:]):
        t2 = font_sm.render(msg, True, C_GRAY)
        screen.blit(t2, (WIDTH//2-t2.get_width()//2, 380+i*22))

    if not grabbing_done:
        return pygame.Rect(WIDTH//2-160,210,140,58), pygame.Rect(WIDTH//2+20,210,140,58)
    return None, None

# ===== 大厅界面 =====
# 全局滚动偏移
prep_scroll = 0

def draw_prep_phase():
    """对局前道具准备阶段：选择携带的主动/被动道具，支持滚动"""
    global prep_active, prep_passive, prep_confirmed, my_items, screen_state, game_phase, prep_scroll
    from items import PASSIVE_ITEMS as _PI_prep, ITEMS as _ITEMS_prep
    draw_background()
    mx,my_p = pygame.mouse.get_pos()

    # 标题和倒计时
    draw_text_shadow(screen,"⚔️ 对局准备",font_xl,C_GOLD,WIDTH//2-font_xl.size("⚔️ 对局准备")[0]//2,18)
    _remain = max(0, 60 - int((anim_tick - prep_start_time) / 60))
    _sub = f"选择本局携带的道具（各限1个主动/1个被动）  剩余 {_remain} 秒"
    screen.blit(font_md.render(_sub,True,C_GRAY),(WIDTH//2-font_md.size(_sub)[0]//2,66))

    from items import PASSIVE_ITEMS as _PI_prep2
    actives  = [(n,c) for n,c in my_items.items() if c>0 and n not in _PI_prep2 and n!="命运盲盒"]
    passives = [(n,c) for n,c in my_items.items() if c>0 and n in _PI_prep2]

    # 可滚动区域
    SCROLL_TOP = 100
    SCROLL_BOT = HEIGHT - 180  # 留出底部摘要+按钮
    VISIBLE_H   = SCROLL_BOT - SCROLL_TOP
    ITEM_H      = 70
    COL_W       = 320
    max_rows    = max(len(actives), len(passives))
    total_h     = max_rows * ITEM_H + 80  # 额外padding确保最后一项可完整滚入
    max_scroll  = max(0, total_h - VISIBLE_H)
    prep_scroll = max(0, min(prep_scroll, max_scroll))

    # 裁剪区域
    clip_rect = pygame.Rect(0, SCROLL_TOP, WIDTH, VISIBLE_H)
    screen.set_clip(clip_rect)

    lx = 40; rx2 = WIDTH//2 + 20
    actives_rects=[]; passives_rects=[]

    # 左栏标题
    ly = SCROLL_TOP + 8 - prep_scroll
    screen.blit(font_md.render("主动道具",True,C_GOLD),(lx, ly)); ly+=38
    if not actives:
        screen.blit(font_sm.render("（无）",True,C_GRAY),(lx+10,ly))
    for iname,cnt in actives:
        item_data=_ITEMS_prep.get(iname,{})
        r=pygame.Rect(lx,ly,COL_W,58)
        selected=prep_active==iname
        col=C_READY if selected else C_DARKGRAY
        draw_rect_alpha(screen,(0,0,0),(r.x,r.y,r.w,r.h),200,8)
        pygame.draw.rect(screen,col,r,2,border_radius=8)
        em=item_data.get("emoji","🃏")
        screen.blit(font_md.render(f"{em} {iname} ×{cnt}",True,C_WHITE if selected else C_GRAY),(r.x+10,r.y+6))
        screen.blit(font_sm.render(item_data.get("desc","")[:30],True,(180,180,180)),(r.x+10,r.y+32))
        if r.collidepoint(mx,my_p): pygame.draw.rect(screen,C_GOLD,r,1,border_radius=8)
        actives_rects.append((r,iname))
        ly+=ITEM_H

    # 右栏
    ry2 = SCROLL_TOP + 8 - prep_scroll
    screen.blit(font_md.render("被动道具",True,(150,200,255)),(rx2,ry2)); ry2+=38
    if not passives:
        screen.blit(font_sm.render("（无）",True,C_GRAY),(rx2+10,ry2))
    for iname,cnt in passives:
        item_data=_ITEMS_prep.get(iname,{})
        r=pygame.Rect(rx2,ry2,COL_W,58)
        selected=prep_passive==iname
        col=C_READY if selected else C_DARKGRAY
        draw_rect_alpha(screen,(0,0,0),(r.x,r.y,r.w,r.h),200,8)
        pygame.draw.rect(screen,col,r,2,border_radius=8)
        em=item_data.get("emoji","🛡")
        screen.blit(font_md.render(f"{em} {iname} ×{cnt}",True,C_WHITE if selected else C_GRAY),(r.x+10,r.y+6))
        screen.blit(font_sm.render(item_data.get("desc","")[:30],True,(180,180,180)),(r.x+10,r.y+32))
        if r.collidepoint(mx,my_p): pygame.draw.rect(screen,C_GOLD,r,1,border_radius=8)
        passives_rects.append((r,iname))
        ry2+=ITEM_H

    # 滚动条
    if max_scroll > 0:
        sb_x = WIDTH-14; sb_h = VISIBLE_H
        ratio = VISIBLE_H / total_h
        sb_thumb_h = max(30, int(sb_h * ratio))
        sb_thumb_y = SCROLL_TOP + int((prep_scroll / max_scroll) * (sb_h - sb_thumb_h))
        pygame.draw.rect(screen,(60,60,60),(sb_x,SCROLL_TOP,8,sb_h),border_radius=4)
        pygame.draw.rect(screen,C_GOLD,(sb_x,sb_thumb_y,8,sb_thumb_h),border_radius=4)

    screen.set_clip(None)

    # 摘要和按钮（固定底部，不随滚动移动）
    sy=HEIGHT-160
    draw_rect_alpha(screen,C_PANEL,(WIDTH//2-280,sy,560,70),220,10)
    pygame.draw.rect(screen,C_GOLD,(WIDTH//2-280,sy,560,70),1,border_radius=10)
    screen.blit(font_md.render(f"主动: {prep_active or '（未选）'}",True,C_GOLD if prep_active else C_GRAY),(WIDTH//2-260,sy+8))
    screen.blit(font_md.render(f"被动: {prep_passive or '（未选）'}",True,(150,200,255) if prep_passive else C_GRAY),(WIDTH//2-260,sy+38))

    ok_r=pygame.Rect(WIDTH//2-160,HEIGHT-76,160,52)
    skip_r=pygame.Rect(WIDTH//2+10,HEIGHT-76,150,52)
    draw_button(ok_r,"✔ 确认出发",C_READY,ok_r.collidepoint(mx,my_p))
    draw_button(skip_r,"跳过",C_DARKGRAY,skip_r.collidepoint(mx,my_p))

    # 超时自动确认（60秒）
    if prep_start_time > 0 and anim_tick - prep_start_time > 60*60:
        if screen_state == "prep":  # 只触发一次
            screen_state="game"; prep_confirmed=True
            try:
                client.send(b"[PREP_DONE]\n")
                client.send(f"[EQUIPPED]{prep_active}|{prep_passive}\n".encode())
            except: pass

    return ok_r, skip_r, actives_rects, passives_rects

def draw_lobby():
    global spectator_count
    draw_background()
    t="♠ BLACK JACK ♠"
    draw_text_shadow(screen,t,font_xl,C_GOLD,WIDTH//2-font_xl.size(t)[0]//2,30)
    # 左上角返回主菜单
    mx0,my0=pygame.mouse.get_pos()
    back_menu_btn=pygame.Rect(15,15,140,38)
    draw_button(back_menu_btn,"◀ 主菜单",C_DARKGRAY,back_menu_btn.collidepoint(mx0,my0))

    draw_rect_alpha(screen,C_PANEL,(WIDTH//2-220,110,440,390),200,16)
    pygame.draw.rect(screen,C_GOLD,(WIDTH//2-220,110,440,390),2,border_radius=16)

    i1=font_lg.render(f"当前玩家: {total_players} 人",True,C_WHITE)
    screen.blit(i1,(WIDTH//2-i1.get_width()//2,132))
    i2=font_lg.render(f"已准备: {ready_players} / {total_players}",True,C_GREEN2)
    screen.blit(i2,(WIDTH//2-i2.get_width()//2,172))

    if ready_players == total_players and total_players >= 2:
        wt = font_xl.render("✅ 全员准备！即将开局", True, C_GREEN2)
    elif total_players < 2:
        wt = font_xl.render("等待更多玩家加入...", True, C_GRAY)
    else:
        wt = font_xl.render(f"等待所有人准备 ({ready_players}/{total_players})", True, C_YELLOW)
    screen.blit(wt,(WIDTH//2-wt.get_width()//2,215))

    bx,by,bw,bh=WIDTH//2-160,278,320,18
    pygame.draw.rect(screen,C_DARKGRAY,(bx,by,bw,bh),border_radius=10)
    if total_players>0:
        pygame.draw.rect(screen,C_READY2,(bx,by,int(bw*ready_players/total_players),bh),border_radius=10)
    pygame.draw.rect(screen,C_GOLD,(bx,by,bw,bh),2,border_radius=10)

    spec_str = f"   👁 观战: {spectator_count}" if spectator_count > 0 else ""
    nt=font_md.render(f"玩家: {my_name}   筹码: {money}{spec_str}",True,C_GOLD2)
    screen.blit(nt,(WIDTH//2-nt.get_width()//2,310))

    st=font_md.render("✅ 等待其他玩家准备..." if is_ready else "点击下方按钮准备游戏",
                      True, C_GREEN2 if is_ready else C_GRAY)
    screen.blit(st,(WIDTH//2-st.get_width()//2,348))

    ready_btn=pygame.Rect(WIDTH//2-110,390,220,52)
    mx,my_p=pygame.mouse.get_pos()
    draw_button(ready_btn,"取消准备" if is_ready else "✔  准备",
                C_UNREADY if is_ready else C_READY,ready_btn.collidepoint(mx,my_p))

    for i,msg in enumerate(log[-3:]):
        t2=font_sm.render(msg,True,C_GRAY)
        screen.blit(t2,(WIDTH//2-t2.get_width()//2,468+i*22))

    # 右下角：修改信息 + 商店 + 排行榜
    edit_btn=pygame.Rect(WIDTH-175,HEIGHT-55,160,42)
    draw_button(edit_btn,"✏ 修改信息",C_ORANGE,edit_btn.collidepoint(mx,my_p))
    shop_btn=pygame.Rect(WIDTH-175,HEIGHT-105,160,42)
    draw_button(shop_btn,"🏪 商店",C_TABLE2,shop_btn.collidepoint(mx,my_p))
    lb_btn=pygame.Rect(WIDTH-175,HEIGHT-155,160,42)
    draw_button(lb_btn,"🏆 排行榜",(80,60,160),lb_btn.collidepoint(mx,my_p))

    # 救济金按钮（筹码低于100时显示）
    relief_btn = None
    if money < 100:
        relief_btn = pygame.Rect(WIDTH-175, HEIGHT-205, 160, 42)
        rc = C_READY if relief_available else C_DARKGRAY
        draw_button(relief_btn, "💰 领救济金", rc, relief_btn.collidepoint(mx,my_p), not relief_available)

    back_menu_btn2=pygame.Rect(15,15,140,38)
    return ready_btn, edit_btn, relief_btn, shop_btn, lb_btn, back_menu_btn2

# ===== 日志绘制（复用于多人/单人）=====
def _draw_log_panel(bottom_y):
    """浮动日志窗口，Tab 开关，居中显示，不占用游戏区域"""
    # Tab 提示（右下角，始终可见）
    th = font_sm.render("[Tab] " + ("关闭日志 ✕" if log_visible else "日志 📋"), True, (120,120,120))
    screen.blit(th, (WIDTH - th.get_width() - 12, HEIGHT - 18))
    if not log_visible:
        return
    PW, PH = 760, 480
    PX, PY = WIDTH//2 - PW//2, HEIGHT//2 - PH//2
    line_h  = 21
    max_vis = (PH - 56) // line_h
    draw_rect_alpha(screen, (0,0,0), (0,0,WIDTH,HEIGHT), 150)
    draw_rect_alpha(screen, C_PANEL, (PX,PY,PW,PH), 240, 14)
    pygame.draw.rect(screen, C_GOLD, (PX,PY,PW,PH), 2, border_radius=14)
    lv = len(log)
    sc_hint = f"  共{lv}条  滚轮翻页" if lv > max_vis else f"  共{lv}条"
    screen.blit(font_lg.render("📋 游戏日志" + sc_hint, True, C_GOLD), (PX+16, PY+10))
    mx2,my2 = pygame.mouse.get_pos()
    close_r = pygame.Rect(PX+PW-60, PY+8, 50, 40)
    draw_button(close_r, "✕", C_UNREADY, close_r.collidepoint(mx2,my2))
    pygame.draw.line(screen, C_GOLD, (PX+8,PY+50), (PX+PW-8,PY+50), 1)
    sc    = max(0, min(log_scroll, max(0, lv - max_vis)))
    start = max(0, lv - max_vis - sc)
    end   = max(0, lv - sc)
    ly    = PY + 56
    clip  = pygame.Rect(PX+6, PY+52, PW-12, PH-56)
    oc    = screen.get_clip()
    screen.set_clip(clip)
    for msg in log[start:end]:
        if "赢" in msg or "✅" in msg:       c = C_GREEN2
        elif "爆" in msg or "输" in msg:     c = C_RED2
        elif "轮到" in msg:                  c = C_YELLOW
        elif "平局" in msg:                  c = C_CYAN
        elif "BJ" in msg or "Black" in msg:  c = C_GOLD2
        elif "👁" in msg:                    c = (80,255,120)
        elif "⏳" in msg or "🛡" in msg:     c = C_CYAN
        elif "━" in msg:                     c = C_GOLD
        else:                                c = (210,210,210)
        screen.blit(font_sm.render(msg, True, c), (PX+12, ly))
        ly += line_h
    screen.set_clip(oc)


# ===== 道具面板 rect 计算（不绘制）=====
show_item_panel = False

def _get_item_rects():
    from items import PASSIVE_ITEMS as _PI
    # 对局中且已确认携带，只显示携带的道具
    if prep_confirmed and screen_state == "game":
        _allowed = set()
        if prep_active: _allowed.add(prep_active)
        if prep_passive: _allowed.add(prep_passive)
        all_items = [(n,c) for n,c in my_items.items() if c>0 and n in _allowed]
    else:
        all_items = [(n,c) for n,c in my_items.items() if c>0]
    main_btn = pygame.Rect(WIDTH-155, HEIGHT-52, 144, 42)
    item_btns = []
    if show_item_panel:
        CARD_H=72; PANEL_W=420
        panel_h = len(all_items)*CARD_H+10
        panel_y = HEIGHT-52-panel_h-6
        panel_x = max(4, WIDTH-PANEL_W-4)
        for i,(iname,cnt) in enumerate(all_items):
            iy  = panel_y+5+i*CARD_H
            ib  = pygame.Rect(panel_x+5, iy, PANEL_W-10, CARD_H-4)
            used    = item_used.get(iname, False)
            passive = iname in _PI
            from items import PASSIVE_ITEMS as _PI2
            phase_ok = True
            if screen_state == "game":
                # 多人模式：按服务器阶段限制
                if iname in _PI2:
                    phase_ok = passive_used_count < 1 or used
                else:
                    phase_ok = (active_used_count < 1 or used) and _item_phase_ok(iname)
            elif screen_state == "solo":
                # 单人模式：阶段限制
                _betting_only = {"搏命契约", "灵魂链接", "沉默干扰器", "吸血印记"}
                _playing_only = {"透视眼镜", "再来一次", "狸猫换太子", "厄运信标",
                                 "第三只手", "命运盲盒", "回炉重造", "强买强卖", "致盲烟雾"}
                if iname in _betting_only:
                    phase_ok = (solo_state == "betting")
                elif iname in _playing_only:
                    phase_ok = (solo_state == "playing")
                # 被动道具始终可用（自动触发）
            item_btns.append((ib, iname, used, passive, phase_ok))
    return main_btn, item_btns

def draw_item_panel():
    from items import PASSIVE_ITEMS as _PI
    # 和 _get_item_rects 保持相同过滤逻辑
    if prep_confirmed and screen_state == "game":
        _allowed2 = set()
        if prep_active: _allowed2.add(prep_active)
        if prep_passive: _allowed2.add(prep_passive)
        all_items = [(n,c) for n,c in my_items.items() if c>0 and n in _allowed2]
    else:
        all_items = [(n,c) for n,c in my_items.items() if c>0]
    if not all_items:
        return None, []
    mx,my_p = pygame.mouse.get_pos()
    main_btn = pygame.Rect(WIDTH-155, HEIGHT-52, 144, 42)
    color = (100,50,150) if show_item_panel else C_TABLE2
    label = "道具 ▲" if show_item_panel else "道具 ▼"
    draw_button(main_btn, label, color, main_btn.collidepoint(mx,my_p))
    item_btns = []
    if show_item_panel:
        CARD_H=72; PANEL_W=420
        panel_h = len(all_items)*CARD_H+10
        panel_y = HEIGHT-52-panel_h-6
        panel_x = max(4, WIDTH-PANEL_W-4)
        draw_rect_alpha(screen, C_PANEL, (panel_x,panel_y,PANEL_W,panel_h), 235, 12)
        pygame.draw.rect(screen, C_GOLD, (panel_x,panel_y,PANEL_W,panel_h), 1, border_radius=12)
        for i,(iname,cnt) in enumerate(all_items):
            item    = ITEMS.get(iname, {})
            used    = item_used.get(iname, False)
            passive = iname in _PI
            from items import PASSIVE_ITEMS as _PI3
            phase_ok = True
            if screen_state == "game":
                if iname in _PI3:
                    phase_ok = passive_used_count < 1 or used
                else:
                    phase_ok = (active_used_count < 1 or used) and _item_phase_ok(iname)
            elif screen_state == "solo":
                _betting_only2 = {"搏命契约", "灵魂链接", "沉默干扰器", "吸血印记"}
                _playing_only2 = {"透视眼镜", "再来一次", "狸猫换太子", "厄运信标",
                                  "第三只手", "命运盲盒", "回炉重造", "强买强卖", "致盲烟雾"}
                if iname in _betting_only2:
                    phase_ok = (solo_state == "betting")
                elif iname in _playing_only2:
                    phase_ok = (solo_state == "playing")
            iy = panel_y+5+i*CARD_H
            ib = pygame.Rect(panel_x+5, iy, PANEL_W-10, CARD_H-4)
            if used:       bg_c=(35,35,50);   border_c=C_DARKGRAY
            elif passive:  bg_c=(20,40,70);   border_c=C_CYAN
            elif not phase_ok: bg_c=(40,30,20); border_c=(100,80,40)
            else:          bg_c=(15,45,25);   border_c=C_GOLD
            draw_rect_alpha(screen, bg_c, (ib.x,ib.y,ib.w,ib.h), 210, 6)
            pygame.draw.rect(screen, border_c, ib, 1, border_radius=6)
            emoji  = item.get('emoji','')
            name_c = C_GRAY if used else C_WHITE
            screen.blit(font_md.render(f"{emoji} {iname}", True, name_c), (ib.x+8, ib.y+5))
            if used:       tag_t = font_sm.render("已用", True, C_GRAY)
            elif passive:  tag_t = font_sm.render("被动自动触发", True, C_CYAN)
            elif not phase_ok:
                rules = {"搏命契约":"下注可用","灵魂链接":"下注可用",
                         "透视眼镜":"你的回合","再来一次":"你的回合",
                         "强买强卖":"他人回合","致盲烟雾":"他人回合","移花接木":"你的回合"}
                tag_t = font_sm.render(f"锁 {rules.get(iname,'')}", True, (150,120,60))
            else:          tag_t = font_sm.render(f"x{cnt}  点击使用", True, C_GREEN2)
            screen.blit(tag_t, (ib.x+ib.w-tag_t.get_width()-8, ib.y+6))
            desc = item.get("desc","")
            desc_clip = pygame.Rect(ib.x+8, ib.y+30, ib.w-16, 22)
            oc = screen.get_clip(); screen.set_clip(desc_clip)
            screen.blit(font_sm.render(desc, True, (160,160,160)), (ib.x+8, ib.y+30))
            screen.set_clip(oc)
            item_btns.append((ib, iname, used, passive, phase_ok))
    return main_btn, item_btns

# ===== 目标选择弹窗 =====
def draw_target_select():
    """选择道具目标玩家弹窗"""
    mx2,my2 = pygame.mouse.get_pos()
    # 目标列表：场上所有玩家（含庄家/系统）排除自己
    # 从排行榜数据获取所有玩家名，排除自己
    _all_names = list(leaderboard_data.get("chips", {}).keys())
    targets = [p for p in _all_names if p != my_name]
    if banker_name and banker_name not in targets and banker_name != my_name:
        targets.append(banker_name)
    if not targets:
        targets = ["系统"]

    item_data = ITEMS.get(target_select_item, {})
    em = item_data.get("emoji","🃏")
    PW = 360; PH = 80 + len(targets)*64 + 20
    PX = WIDTH//2 - PW//2; PY = HEIGHT//2 - PH//2
    draw_rect_alpha(screen,(0,0,0),(0,0,WIDTH,HEIGHT),150)
    draw_rect_alpha(screen,C_PANEL,(PX,PY,PW,PH),240,14)
    pygame.draw.rect(screen,C_GOLD,(PX,PY,PW,PH),2,border_radius=14)
    title = font_lg.render(f"{em} {target_select_item} — 选择目标",True,C_GOLD)
    screen.blit(title,(PX+PW//2-title.get_width()//2, PY+14))
    btns = []
    for i,tname in enumerate(targets):
        r = pygame.Rect(PX+30, PY+60+i*64, PW-60, 50)
        hover = r.collidepoint(mx2,my2)
        draw_rect_alpha(screen,(40,40,60),(r.x,r.y,r.w,r.h),220,10)
        pygame.draw.rect(screen,C_GOLD if hover else C_TABLE2,r,2,border_radius=10)
        nt = font_lg.render(tname,True,C_WHITE)
        screen.blit(nt,(r.x+r.w//2-nt.get_width()//2, r.y+10))
        btns.append((r, tname))
    cancel_r = pygame.Rect(PX+PW//2-60, PY+PH-52, 120, 38)
    draw_button(cancel_r,"取消",C_DARKGRAY,cancel_r.collidepoint(mx2,my2))
    return btns, cancel_r

# ===== 外围下注弹窗 =====
def draw_side_bet_popup():
    """外围下注弹窗：选择目标/类型/金额"""
    PW,PH=500,280; PX,PY=WIDTH//2-PW//2,HEIGHT//2-PH//2
    draw_rect_alpha(screen,(0,0,0),(0,0,WIDTH,HEIGHT),160)
    draw_rect_alpha(screen,C_PANEL,(PX,PY,PW,PH),240,14)
    pygame.draw.rect(screen,(200,150,0),(PX,PY,PW,PH),2,border_radius=14)
    screen.blit(font_lg.render("🎲 外围下注",True,C_GOLD),(PX+PW//2-font_lg.size("🎲 外围下注")[0]//2,PY+12))
    screen.blit(font_sm.render("目标: "+side_bet_target if side_bet_target else "点击目标玩家名",True,C_WHITE),(PX+20,PY+58))
    mx2,my2=pygame.mouse.get_pos()
    # 押爆/押赢按钮
    bust_r=pygame.Rect(PX+30,PY+90,190,44)
    win_r =pygame.Rect(PX+280,PY+90,190,44)
    bust_c=(180,40,40) if side_bet_type=="bust" else C_DARKGRAY
    win_c =(40,160,80) if side_bet_type=="win"  else C_DARKGRAY
    draw_button(bust_r,"💀 押他爆牌",bust_c,bust_r.collidepoint(mx2,my2))
    draw_button(win_r, "🏆 押他赢",  win_c, win_r.collidepoint(mx2,my2))
    # 金额输入
    screen.blit(font_md.render("下注金额:",True,C_WHITE),(PX+20,PY+152))
    ir2=pygame.Rect(PX+120,PY+148,200,40)
    pygame.draw.rect(screen,(30,60,40),ir2,border_radius=8)
    pygame.draw.rect(screen,C_GOLD,ir2,2,border_radius=8)
    screen.blit(font_lg.render(side_bet_input or "100",True,C_WHITE if side_bet_input else C_GRAY),(ir2.x+10,ir2.y+7))
    # 确认/取消
    ok_r=pygame.Rect(PX+80,PY+212,140,46)
    ca_r=pygame.Rect(PX+280,PY+212,140,46)
    ok_dis = not (side_bet_target and side_bet_type and side_bet_input)
    draw_button(ok_r,"✔ 确认下注",C_READY if not ok_dis else C_DARKGRAY,ok_r.collidepoint(mx2,my2),ok_dis)
    draw_button(ca_r,"✘ 取消",C_UNREADY,ca_r.collidepoint(mx2,my2))
    return bust_r,win_r,ok_r,ca_r,ir2

# ===== 命运盲盒结果处理 =====
def _handle_blindbox_result(result, shop_name):
    global money, is_blinded, available_opts, my_items, lucky_buff_active, lucky_buff_games, log_visible
    parts = result.split(":", 1)
    tier, detail = parts[0], parts[1] if len(parts)>1 else ""
    log_visible = True; log_scroll_tmp = 0
    if tier == "superjackpot":
        lucky_buff_active = True; lucky_buff_games = 3
        log.append("📦 ⭐ 特等奖！接下来连续3局，每局都有 88.8% 概率直接抽到黑杰克！")
        log.append("   欧皇附体，连庄家都开始冒汗了。")
        add_particles(WIDTH//2, HEIGHT//2, (255,215,0), 50)
        add_particles(WIDTH//2, HEIGHT//2, (255,100,255), 30)
    elif tier == "jackpot":
        log.append(f"📦 🥇 大奖！获得【{detail}】！（3局内有效，无冷却）")
        log.append("   这波真赚了。")
        add_particles(WIDTH//2, HEIGHT//2, C_GOLD2, 30)
        _reload_cosmetics()
    elif tier == "normal":
        log.append(f"📦 🥈 保本！获得【{detail}】（3局内有效，无冷却）")
        _reload_cosmetics()
    elif tier == "nothing":
        log.append("📦 🥉 谢谢参与！（什么都没有）")
        log.append("   一张纸条写着：下次一定。")
    elif tier == "curse":
        if detail == "leak":
            penalty = max(100, int(money * 0.10))
            money -= penalty
            save_record(shop_name.replace("__custom__",""), money)
            log.append(f"📦 💀 诅咒！漏财！扣除 {fmt_chips(penalty)} 筹码！")
            add_particles(WIDTH//2, HEIGHT//2, C_RED2, 20)
        elif detail == "blind":
            is_blinded = True
            log.append("📦 💀 诅咒！小丑的戏法！你看不见自己的点数了！")
        elif detail == "forced_hit":
            log.append("📦 💀 诅咒！上头了！下局开局将自动多摸一张牌！")
    # 多人联机下，同步会影响服务器对局逻辑的盲盒效果
    try:
        if connected and client and screen_state in ("prep","game") and tier in ("superjackpot","curse"):
            if tier == "superjackpot":
                _target_gid = current_game_id if screen_state == "prep" else current_game_id + 1
                client.send(f"[SYNC_BOX_EFFECT]superjackpot|{_target_gid}\n".encode())
            elif tier == "curse" and detail == "forced_hit":
                _target_gid = current_game_id if screen_state == "prep" else current_game_id + 1
                client.send(f"[SYNC_BOX_EFFECT]forced_hit|{_target_gid}\n".encode())
            elif tier == "curse" and detail == "blind":
                # 致盲只影响本地显示，不需要同步给服务器开局逻辑
                pass
    except:
        pass

# ===== 商店界面 =====

def draw_shop():
    global shop_scroll, shop_tab
    PW,PH=820,560
    PX,PY=WIDTH//2-PW//2,HEIGHT//2-PH//2
    draw_rect_alpha(screen,(0,0,0),(0,0,WIDTH,HEIGHT),160)
    draw_rect_alpha(screen,C_PANEL,(PX,PY,PW,PH),245,14)
    pygame.draw.rect(screen,C_GOLD,(PX,PY,PW,PH),2,border_radius=14)
    screen.blit(font_xl.render("黑市商店",True,C_GOLD),(PX+PW//2-font_xl.size("黑市商店")[0]//2,PY+12))
    screen.blit(font_md.render(f"筹码: {fmt_chips(money)}",True,C_GOLD2),(PX+16,PY+16))
    mx,my_p=pygame.mouse.get_pos()
    close_r=pygame.Rect(PX+PW-60,PY+8,50,40)
    draw_button(close_r,"✕",C_UNREADY,close_r.collidepoint(mx,my_p))
    tabs=[("items","道具"),("cardbacks","卡背"),("tablecloth","桌布"),("achievements","成就")]
    tab_w=PW//len(tabs)
    for i,(key,label) in enumerate(tabs):
        tr=pygame.Rect(PX+i*tab_w,PY+58,tab_w,36)
        tc=C_GOLD if shop_tab==key else C_TABLE2
        draw_button(tr,label,tc,tr.collidepoint(mx,my_p))
    pygame.draw.line(screen,C_GOLD,(PX,PY+94),(PX+PW,PY+94),1)

    sn = _shop_name()
    y=PY+100-shop_scroll
    if shop_tab=="items":
        sn2 = _shop_name()
        is_custom = sn2.startswith("__custom__")
        # 个人专属商店：普通模式只显示推送的3个道具+盲盒，自定义显示全部
        if is_custom:
            shop_items_list = list(ITEMS.items())
            _gid_shop = None
        else:
            # 绘制和点击统一使用同一个商店局号，避免串局/未定义变量
            _gid_shop = _shop_game_id()
            personal = getattr(Shop,"get_personal_shop",lambda a,b,c:{"命运盲盒":{"price":300,"qty":99}})(sn2, _gid_shop, money)
            shop_items_list = []
            # 盲盒始终第一个
            if "命运盲盒" in ITEMS:
                shop_items_list.append(("命运盲盒", ITEMS["命运盲盒"]))
            for iname in personal:
                if iname != "命运盲盒" and iname in ITEMS:
                    shop_items_list.append((iname, ITEMS[iname]))
        for iname,item in shop_items_list:
            if y>PY+PH-10: break
            if y+68<PY+100: y+=78; continue
            dyn_price = item['price'] if is_custom else getattr(Shop,"get_dynamic_price",lambda a,b:ITEMS.get(a,{}).get("price",999))(iname,money)
            cd = 0 if is_custom else Shop.get_item_cooldown(sn2,iname)
            ir=pygame.Rect(PX+20,y,PW-40,68)
            # 盲盒特殊背景
            if iname=="命运盲盒":
                box_bought = 0 if is_custom else getattr(Shop,"get_blindbox_purchase_count",lambda a,b:0)(sn2, _gid_shop)
                box_remain = max(0, 3 - box_bought)
                draw_rect_alpha(screen,(60,0,80),(PX+20,y,PW-40,68),200,8)
                pygame.draw.rect(screen,(180,0,255),(PX+20,y,PW-40,68),1,border_radius=8)
                screen.blit(font_sm.render(f"本局剩余{box_remain}次", True, (200,150,255)), (PX+PW-300,y+38))
            else:
                draw_rect_alpha(screen,(15,40,20),(PX+20,y,PW-40,68),200,8)
                pygame.draw.rect(screen,C_DARKGRAY,(PX+20,y,PW-40,68),1,border_radius=8)
            screen.blit(font_md.render(f"{item['emoji']} {iname}",True,C_WHITE),(PX+30,y+8))
            screen.blit(font_sm.render(item['desc'],True,C_GRAY),(PX+30,y+34))
            have=my_items.get(iname,0)
            screen.blit(font_sm.render(f"持有:{have}",True,C_CYAN),(PX+PW-300,y+16))
            if cd > 0:
                screen.blit(font_sm.render(f"冷却{cd}局",True,C_RED2),(PX+PW-300,y+38))
            # 价格标签
            base_p = item['price']
            if not is_custom and dyn_price > base_p:
                price_color = (220,100,0)  # 橙色：涨价
                price_lbl = f"购买 {dyn_price}↑"
            elif iname=="命运盲盒":
                price_color = (200,0,255)
                price_lbl = f"开箱 {dyn_price}"
            else:
                price_color = C_READY
                price_lbl = f"购买 {dyn_price}"
            can_buy = money>=dyn_price and cd==0
            buy_r=pygame.Rect(PX+PW-140,y+16,120,36)
            draw_button(buy_r, price_lbl, price_color if can_buy else C_DARKGRAY,
                        buy_r.collidepoint(mx,my_p) and can_buy, not can_buy)
            y+=78
    elif shop_tab=="cardbacks":
        for bname,bdata in CARD_BACKS.items():
            if y>PY+PH-10: break
            if y+70<PY+100: y+=80; continue
            owned=bname in my_owned_backs
            equipped=bname==my_card_back
            ir=pygame.Rect(PX+20,y,PW-40,72)
            bg=(20,40,60) if equipped else (15,30,20)
            draw_rect_alpha(screen,bg,(PX+20,y,PW-40,72),200,8)
            bc=C_GOLD if equipped else C_DARKGRAY
            pygame.draw.rect(screen,bc,(PX+20,y,PW-40,72),1,border_radius=8)
            screen.blit(font_md.render(bname,True,C_WHITE if owned else C_GRAY),(PX+30,y+8))
            screen.blit(font_sm.render(bdata['desc'],True,(150,150,150)),(PX+30,y+36))
            if equipped:
                screen.blit(font_sm.render("已装备",True,C_GOLD),(PX+PW-240,y+28))
            elif owned:
                eq_r=pygame.Rect(PX+PW-130,y+18,110,35)
                draw_button(eq_r,"装备",C_TABLE2,eq_r.collidepoint(mx,my_p))
            else:
                can_buy=money>=bdata['price']
                buy_r=pygame.Rect(PX+PW-130,y+18,110,35)
                draw_button(buy_r,f"{bdata['price']}",C_READY if can_buy else C_DARKGRAY,
                            buy_r.collidepoint(mx,my_p) and can_buy, not can_buy)
            y+=80
    elif shop_tab=="tablecloth":
        for tname,tdata in TABLECLOTHS.items():
            if y>PY+PH-10: break
            if y+62<PY+100: y+=72; continue
            owned=tname in my_owned_cloths
            equipped=tname==my_tablecloth
            draw_rect_alpha(screen,(15,30,20),(PX+20,y,PW-40,62),200,8)
            pygame.draw.rect(screen,C_GOLD if equipped else C_DARKGRAY,(PX+20,y,PW-40,62),1,border_radius=8)
            pygame.draw.rect(screen,tdata['color'],(PX+30,y+12,40,38),border_radius=6)
            screen.blit(font_md.render(tdata['name'],True,C_WHITE),(PX+80,y+18))
            if equipped:
                screen.blit(font_sm.render("已装备",True,C_GOLD),(PX+PW-240,y+22))
            elif owned:
                eq_r=pygame.Rect(PX+PW-130,y+14,110,34)
                draw_button(eq_r,"装备",C_TABLE2,eq_r.collidepoint(mx,my_p))
            else:
                can_buy=money>=tdata['price'] and tdata['price']>0
                buy_r=pygame.Rect(PX+PW-130,y+14,110,34)
                lbl=f"{tdata['price']}" if tdata['price']>0 else "免费"
                draw_button(buy_r,lbl,C_READY if can_buy else C_DARKGRAY,
                            buy_r.collidepoint(mx,my_p),not can_buy and tdata['price']>0)
            y+=72
    elif shop_tab=="achievements":
        for ach_key,ach in ACHIEVEMENTS.items():
            if y>PY+PH-10: break
            if y+62<PY+100: y+=72; continue
            have=ach_key in my_achievements
            draw_rect_alpha(screen,(20,40,15) if have else (30,25,15),(PX+20,y,PW-40,62),200,8)
            pygame.draw.rect(screen,C_GOLD if have else C_DARKGRAY,(PX+20,y,PW-40,62),1,border_radius=8)
            screen.blit(font_md.render(f"{ach['emoji']} {ach['name']}",True,C_GOLD if have else C_GRAY),(PX+30,y+8))
            screen.blit(font_sm.render(ach['desc'],True,C_WHITE if have else (100,100,100)),(PX+30,y+34))
            if have: screen.blit(font_sm.render("已解锁",True,C_GREEN2),(PX+PW-150,y+22))
            y+=72
    return close_r

# ===== 排行榜 =====
def draw_leaderboard():
    PW,PH=700,480; PX,PY=WIDTH//2-PW//2,HEIGHT//2-PH//2
    draw_rect_alpha(screen,(0,0,0),(0,0,WIDTH,HEIGHT),160)
    draw_rect_alpha(screen,C_PANEL,(PX,PY,PW,PH),245,14)
    pygame.draw.rect(screen,C_GOLD,(PX,PY,PW,PH),2,border_radius=14)
    screen.blit(font_xl.render("排行榜",True,C_GOLD),(PX+PW//2-font_xl.size("排行榜")[0]//2,PY+12))
    mx,my_p=pygame.mouse.get_pos()
    close_r=pygame.Rect(PX+PW-60,PY+8,50,40)
    draw_button(close_r,"✕",C_UNREADY,close_r.collidepoint(mx,my_p))
    pygame.draw.line(screen,C_GOLD,(PX+8,PY+58),(PX+PW-8,PY+58),1)
    cols=[("chips","筹码榜",PX+30),("win_streak","连胜榜",PX+260),("loss_streak","连败榜",PX+490)]
    medals=["🥇","🥈","🥉"]
    for key,label,cx in cols:
        screen.blit(font_md.render(label,True,C_GOLD),(cx,PY+68))
        data=leaderboard_data.get(key,{})
        sorted_d=sorted(data.items(),key=lambda x:-x[1])
        for rank,(name,val) in enumerate(sorted_d[:8]):
            ry=PY+98+rank*40
            medal=medals[rank] if rank<3 else f"{rank+1}."
            c=C_GOLD2 if name==my_name else C_WHITE
            screen.blit(font_sm.render(f"{medal} {name}",True,c),(cx,ry))
            screen.blit(font_sm.render(str(val),True,c),(cx+160,ry))
    return close_r

# ===== 成就弹窗 =====
def draw_ach_popup():
    if not new_achievements: return
    ach_key=new_achievements[-1]
    ach=ACHIEVEMENTS.get(ach_key,{})
    if not ach: return
    elapsed=anim_tick-ach_popup_tick
    if elapsed>200: return
    alpha=min(255,int(255*(1-elapsed/200)))
    pw,ph=360,80; px,py=WIDTH//2-pw//2,120
    draw_rect_alpha(screen,C_PANEL,(px,py,pw,ph),min(220,alpha),12)
    pygame.draw.rect(screen,C_GOLD,(px,py,pw,ph),2,border_radius=12)
    t1=font_md.render(f"成就解锁: {ach['emoji']} {ach['name']}",True,C_GOLD2)
    t2=font_sm.render(ach['desc'],True,C_GRAY)
    screen.blit(t1,(px+pw//2-t1.get_width()//2,py+10))
    screen.blit(t2,(px+pw//2-t2.get_width()//2,py+42))

# ===== 改筹码弹窗 =====
def draw_chips_edit_popup():
    draw_rect_alpha(screen,(0,0,0),(0,0,WIDTH,HEIGHT),160)
    pw,ph=400,180; px,py=WIDTH//2-pw//2,HEIGHT//2-ph//2
    draw_rect_alpha(screen,C_PANEL,(px,py,pw,ph),240,14)
    pygame.draw.rect(screen,C_GOLD,(px,py,pw,ph),2,border_radius=14)
    screen.blit(font_lg.render("设置筹码",True,C_GOLD),(px+pw//2-font_lg.size("设置筹码")[0]//2,py+14))
    screen.blit(font_sm.render("输入金额（支持K/M/B/T），Enter确认",True,C_GRAY),(px+20,py+52))
    ir=pygame.Rect(px+20,py+80,pw-40,46)
    pygame.draw.rect(screen,(20,50,30),ir,border_radius=8)
    pygame.draw.rect(screen,C_GOLD,ir,2,border_radius=8)
    screen.blit(font_lg.render(edit_chips_input or "0",True,C_WHITE),(ir.x+12,ir.y+9))
    mx,my_p=pygame.mouse.get_pos()
    ok_r=pygame.Rect(px+pw//2-110,py+138,100,36)
    ca_r=pygame.Rect(px+pw//2+10,py+138,100,36)
    draw_button(ok_r,"确认",C_READY,ok_r.collidepoint(mx,my_p))
    draw_button(ca_r,"取消",C_UNREADY,ca_r.collidepoint(mx,my_p))
    return ok_r, ca_r

# ===== 单人模式逻辑 =====
def solo_new_game():
    global solo_state,solo_hand,solo_dealer_hand,solo_bet,solo_deck
    global solo_result_msg,my_turn,solo_dealer_upcard_hidden,available_opts
    global item_used,log_scroll,active_used_count,passive_used_count,current_game_id
    global dealer_peek_hand,peek_result,is_blinded
    from game_logic import get_deck
    solo_deck=[]; [solo_deck.extend(get_deck()) for _ in range(6)]
    random.shuffle(solo_deck)
    solo_hand=[]; solo_dealer_hand=[]; solo_bet=0; solo_result_msg=""
    my_turn=False; solo_state="betting"; solo_dealer_upcard_hidden=True
    available_opts=[]; item_used={}; log_scroll=0
    active_used_count=0; passive_used_count=0
    current_game_id += 1  # 每局新ID，商店重新随机
    # 每局重置盲盒限购计数
    try:
        _bc2 = getattr(Shop,"_box_buy_count",None)
        if _bc2 is not None:
            keys_del = [k for k in _bc2 if k.startswith(my_name+"_")]
            for k in keys_del: del _bc2[k]
    except: pass
    # 重置商店道具池缓存（每局刷新一次）
    _clear_shop_cache()
    if solo_submode == "normal":
        try: getattr(Shop,"tick_cooldowns",lambda a:None)(my_name)
        except: pass
    dealer_peek_hand=[]; peek_result=""
    is_blinded=False  # 每局重置致盲状态
    sep="━━━━ 新一局 ━━━━"
    sep_indices=[i for i,l in enumerate(log) if sep in l]
    if len(sep_indices)>=1: log[:]=log[sep_indices[-1]:]
    elif len(log)>30: log[:]=log[-30:]

def _solo_update_opts():
    global available_opts
    from game_logic import can_split
    opts=["HIT","STAND"]
    if len(solo_hand)==2 and money>=solo_bet: opts.append("DOUBLE")
    if len(solo_hand)==2 and can_split(solo_hand) and money>=solo_bet: opts.append("SPLIT")
    if len(solo_hand)==2: opts.append("SURRENDER")
    available_opts=opts

def _solo_shop_name():
    return ("__custom__"+my_name) if solo_submode=="custom" else my_name

def _solo_use_passive(iname):
    global passive_used_count
    n=_solo_shop_name()
    Shop.use_item(n,iname)
    _reload_cosmetics()
    item_used[iname]=True; passive_used_count+=1

def solo_deal():
    global solo_hand,solo_dealer_hand,solo_state,available_opts,my_turn
    global dealer_peek_hand,peek_result
    from game_logic import calc,is_blackjack
    solo_hand=[solo_deck.pop(),solo_deck.pop()]
    solo_dealer_hand=[solo_deck.pop(),solo_deck.pop()]
    # 特等奖：接下来连续3局，每局88.8%概率直接抽到BJ
    try:
        _sn_lucky = _solo_shop_name()
        if getattr(Shop,"consume_lucky_buff",lambda a,b:False)(_sn_lucky, current_game_id):
            import random as _rnd
            if _rnd.random() < 0.888:
                _aces = [c for c in solo_deck if str(c).startswith("A")]
                _tens = [c for c in solo_deck if str(c)[:-1] in ("10","J","Q","K")]
                if _aces and _tens:
                    _a = _aces[0]; _t = _tens[0]
                    solo_deck.remove(_a); solo_deck.remove(_t)
                    solo_hand=[_a,_t] if _rnd.random()<0.5 else [_t,_a]
    except:
        pass
    # 诅咒：上头了，开局自动多摸一张
    try:
        _sn_force = _solo_shop_name()
        if getattr(Shop,"consume_forced_opening_hit",lambda a,b:False)(_sn_force, current_game_id) and solo_deck:
            solo_hand.append(solo_deck.pop())
            log.append("📦 💀 上头了生效：本局开局自动多摸一张牌！")
    except:
        pass
    dealer_peek_hand=[]; peek_result=""
    solo_state="playing"; my_turn=True
    _solo_update_opts()
    # 发牌动画：初始两张牌依次从旋涡中出现；若有第3张则继续补播
    _cw2,_sp2=72,12
    _tw2=max(2,len(solo_hand))*_cw2+(max(2,len(solo_hand))-1)*_sp2
    _sx2=WIDTH//2-_tw2//2; _cy2=330
    card_reveal_queue.clear()
    card_reveal_pending.clear()
    _full_hand = list(solo_hand)
    solo_hand.clear()
    if _full_hand:
        queue_card_reveal(_full_hand[0], _sx2, _cy2, _cw2, int(_cw2*CARD_H/CARD_W))
    for _idx, _card in enumerate(_full_hand[1:], start=1):
        card_reveal_pending.append((_card, _sx2+_idx*(_cw2+_sp2), _cy2, _cw2, int(_cw2*CARD_H/CARD_W), 25*_idx, _full_hand))
    log.append("━━━━ 新一局 ━━━━")
    try:
        if getattr(Shop,"get_lucky_buff",lambda a:None)(_solo_shop_name()):
            log.append("⭐ 特等奖加持中！连续3局，每局都有 88.8% 概率直接黑杰克")
    except:
        pass
    if is_blinded:
        log.append(f"你的手牌: ??? (小丑的戏法，点数隐藏)")
    else:
        log.append(f"你的手牌: {_full_hand} ({calc(_full_hand)}点)")
    log.append(f"庄家明牌: {solo_dealer_hand[1]}")

def solo_hit():
    global solo_state,my_turn,available_opts,money,solo_result_msg,item_used,passive_used_count
    from game_logic import calc,is_five_card_charlie
    card=solo_deck.pop()
    # 要牌动画：先播动画，动画结束后才把牌加入手牌显示
    _cw3,_sp3=72,12
    _n=len(solo_hand)
    _tw3=(_n+1)*_cw3+_n*_sp3
    _sx3=WIDTH//2-_tw3//2
    _cy3=330
    # 先加入手牌（用于计算位置），动画期间牌已在手牌里但动画覆盖显示
    solo_hand.append(card)
    # 动画：用正确位置（包含新牌后的位置）
    _n2=len(solo_hand)-1
    _tw3b=len(solo_hand)*_cw3+(len(solo_hand)-1)*_sp3
    _sx3b=WIDTH//2-_tw3b//2
    queue_card_reveal(card, _sx3b+_n2*(_cw3+_sp3), _cy3, _cw3, int(_cw3*CARD_H/CARD_W))
    if is_blinded:
        log.append(f"你摸了一张牌（小丑戏法：点数隐藏）")
    else:
        log.append(f"你摸了 {card} -> {calc(solo_hand)}点")
    val=calc(solo_hand)
    if val>21:
        if my_items.get("时光倒流",0)>0 and not item_used.get("时光倒流"):
            _solo_use_passive("时光倒流")
            solo_hand.pop(); solo_deck.insert(0,card)
            log.append("⏳ 时光倒流触发！退回了爆牌的牌，强制停牌")
            solo_dealer_turn(); return
        solo_result_msg="💥 爆牌，输了"
        if my_items.get("金蝉脱壳",0)>0 and not item_used.get("金蝉脱壳"):
            _solo_use_passive("金蝉脱壳")
            global money
            money+=solo_bet; solo_result_msg="🛡 金蝉脱壳！爆牌退还赌注"
            log.append("🛡 金蝉脱壳触发！")
        solo_end_round(); return
    if is_five_card_charlie(solo_hand):
        solo_result_msg="🐉 五龙！赢2倍"; _solo_settle(2.0); return
    available_opts=["HIT","STAND"]

def solo_stand():
    global my_turn
    from game_logic import calc
    if is_blinded:
        log.append("你停牌（点数隐藏）")
    else:
        log.append(f"你停牌，点数: {calc(solo_hand)}")
    my_turn=False; solo_dealer_turn()

def solo_double():
    global money,solo_bet,solo_result_msg
    from game_logic import calc
    money-=solo_bet; solo_bet*=2
    save_record_solo(my_name, money)  # 加倍立即存档
    card=solo_deck.pop(); solo_hand.append(card)
    log.append(f"加倍！摸了 {card} -> {calc(solo_hand)}点")
    if calc(solo_hand)>21:
        solo_result_msg="💥 加倍爆牌"; solo_end_round()
    else:
        solo_dealer_turn()

def solo_surrender():
    global money,solo_bet,solo_result_msg
    refund=solo_bet//2; money+=refund; solo_bet=0
    solo_result_msg=f"🏳 投降，返还 {refund} 筹码"
    log.append(solo_result_msg); solo_end_round()

def solo_dealer_turn():
    global solo_dealer_upcard_hidden
    from game_logic import dealer_should_hit,calc
    solo_dealer_upcard_hidden=False
    log.append(f"庄家翻开暗牌: {solo_dealer_hand[0]}")
    while dealer_should_hit(solo_dealer_hand):
        card=solo_deck.pop(); solo_dealer_hand.append(card)
        log.append(f"庄家摸牌: {card} -> {calc(solo_dealer_hand)}点")
    if calc(solo_dealer_hand)>21: log.append("💥 庄家爆牌！")
    _solo_settle()

def _solo_settle(force_multiplier=None):
    global money,solo_result_msg,solo_state,my_turn
    from game_logic import calc,is_blackjack,is_five_card_charlie
    p_val=calc(solo_hand); d_val=calc(solo_dealer_hand); d_bust=d_val>21
    bet=solo_bet
    mult=3.5 if item_used.get("搏命契约") else 1.0
    if force_multiplier is not None:
        gain=int(bet*force_multiplier*mult); money+=gain
        save_record_solo(my_name,money); solo_state="result"; my_turn=False
        if gain>bet: add_particles(WIDTH//2,HEIGHT//2,C_GOLD2,20); return
    # 点数修正
    if my_items.get("点数修正",0)>0 and not item_used.get("点数修正"):
        for delta in [+1,-1]:
            adj=p_val+delta
            if 1<=adj<=21:
                if (not d_bust and adj>d_val) or (d_bust and adj<=21):
                    if p_val>21 or (not d_bust and p_val<=d_val):
                        p_val=adj; _solo_use_passive("点数修正")
                        log.append(f"📏 点数修正！调整为{p_val}点"); break
    if p_val>21:
        gain=0; solo_result_msg="💥 爆牌，输了"
        if my_items.get("金蝉脱壳",0)>0 and not item_used.get("金蝉脱壳"):
            _solo_use_passive("金蝉脱壳"); gain=bet
            solo_result_msg="🛡 金蝉脱壳！退还赌注"; money+=gain
    elif is_five_card_charlie(solo_hand):
        gain=int(bet*2*mult); solo_result_msg="🐉 五龙！赢2倍"; money+=gain
    elif is_blackjack(solo_hand) and not is_blackjack(solo_dealer_hand):
        gain=int(bet*2.5*mult); solo_result_msg="BlackJack！赢1.5倍"; money+=gain
    elif is_blackjack(solo_dealer_hand) and not is_blackjack(solo_hand):
        gain=0; solo_result_msg="庄家BJ，输了"
        if my_items.get("金蝉脱壳",0)>0 and not item_used.get("金蝉脱壳"):
            _solo_use_passive("金蝉脱壳"); gain=bet
            solo_result_msg="🛡 金蝉脱壳！退还赌注"; money+=gain
    elif is_blackjack(solo_hand) and is_blackjack(solo_dealer_hand):
        gain=bet; solo_result_msg="双方BJ平局"; money+=gain
    elif d_bust or p_val>d_val:
        # 作弊惩罚：用了主动增益道具（透视/再来一次），赔率减半
        # 但搏命契约激活时豁免惩罚（已承担输3.5倍风险，赢就拿全额）
        used_boost = any(item_used.get(k) for k in ["透视眼镜","再来一次"])
        has_gamble = item_used.get("搏命契约", False)
        if used_boost and solo_submode!="custom" and not has_gamble:
            penalty = 0.5
            suffix  = "（道具惩罚×0.5）"
        else:
            penalty = 1.0
            suffix  = ""
        gain=int(bet*2*mult*penalty)
        solo_result_msg=f"赢了{suffix}{'(搏命×3.5)' if mult>1 else ''}"; money+=gain
    elif p_val==d_val:
        gain=bet; solo_result_msg="平局"; money+=gain
    else:
        gain=0; solo_result_msg="输了"
        if my_items.get("金蝉脱壳",0)>0 and not item_used.get("金蝉脱壳"):
            _solo_use_passive("金蝉脱壳"); gain=bet
            solo_result_msg="🛡 金蝉脱壳！退还赌注"; money+=gain
        elif mult>1:
            extra=int(bet*(mult-1)); money-=extra
            solo_result_msg=f"输了(搏命惩罚额外扣{fmt_chips(extra)})"
    if is_blinded:
        log.append(f"小丑戏法解除！你的真实点数: {calc(solo_hand)}")
    log.append(f"庄家{d_val}点 你{p_val}点 -> {solo_result_msg}")
    log.append(f"余额: {fmt_chips(money)}")
    save_record_solo(my_name,money)
    solo_state="result"; my_turn=False
    if gain>bet: add_particles(WIDTH//2,HEIGHT//2,C_GOLD2,20)

def solo_end_round():
    global solo_state,my_turn
    solo_state="result"; my_turn=False

# ===== 单人界面 =====
def draw_solo_game():
    global solo_state
    from game_logic import calc,is_blackjack
    draw_background()
    # 顶部栏
    draw_rect_alpha(screen,C_PANEL,(0,0,WIDTH,70),200)
    pygame.draw.line(screen,C_GOLD,(0,70),(WIDTH,70),2)
    draw_text_shadow(screen,"单人模式",font_lg,C_GOLD,20,18)
    title_disp=f"[{my_title}] {my_name}" if my_title else my_name
    draw_text_shadow(screen,title_disp,font_md,C_CYAN,200,22)
    draw_text_shadow(screen,f"筹码: {fmt_chips(money)}",font_lg,C_GOLD2,WIDTH//2-80,18)
    mx,my_p=pygame.mouse.get_pos()
    back_btn=pygame.Rect(WIDTH-160,78,140,34)
    draw_button(back_btn,"◀ 返回菜单",C_DARKGRAY,back_btn.collidepoint(mx,my_p))
    shop_btn2=None
    if solo_state in ("betting","idle","result"):
        shop_btn2=pygame.Rect(WIDTH-310,78,140,34)
        draw_button(shop_btn2,"商店",C_TABLE2,shop_btn2.collidepoint(mx,my_p))
    edit_chips_btn=None
    if solo_submode=="custom" and solo_state in ("betting","result"):
        edit_chips_btn=pygame.Rect(WIDTH-460,78,140,34)
        draw_button(edit_chips_btn,"改筹码",(100,60,160),edit_chips_btn.collidepoint(mx,my_p))
    # 救济金按钮（人机模式，低于100时显示）
    relief_btn2=None
    if solo_submode=="normal" and money<100 and solo_state in ("betting","result","idle"):
        remain=get_solo_relief_count(my_name)
        relief_btn2=pygame.Rect(15,78,180,34)
        rc2=C_READY if remain>0 else C_DARKGRAY
        draw_button(relief_btn2,f"💰 救济金({remain}次)",rc2,relief_btn2.collidepoint(mx,my_p),remain==0)

    # 庄家区域
    screen.blit(font_md.render("庄家手牌",True,C_GOLD),
                (WIDTH//2-font_md.size("庄家手牌")[0]//2,90))
    if solo_dealer_hand:
        cw,sp=72,12
        total_w=len(solo_dealer_hand)*cw+(len(solo_dealer_hand)-1)*sp
        sx=WIDTH//2-total_w//2
        for i,c in enumerate(solo_dealer_hand):
            if i==0 and solo_dealer_upcard_hidden:
                if dealer_peek_hand:
                    draw_card(sx,110,c)
                    pygame.draw.rect(screen,C_GREEN2,(sx-3,107,CARD_W+6,CARD_H+6),2,border_radius=8)
                else:
                    draw_card(sx,110,c,show_back=True,back_name=my_card_back)
            else:
                draw_card(sx+i*(cw+sp),110,c)
        card_bottom=110+CARD_H+8
        if not solo_dealer_upcard_hidden:
            dv=calc(solo_dealer_hand)
            dc=C_RED2 if dv>21 else C_WHITE
            dt=font_md.render(f"点数: {dv}",True,dc)
            screen.blit(dt,(WIDTH//2-dt.get_width()//2,card_bottom))
        else:
            dt=font_md.render(f"点数: {calc([solo_dealer_hand[1]])}",True,C_WHITE)
            screen.blit(dt,(WIDTH//2-dt.get_width()//2,card_bottom))
        if dealer_peek_hand and solo_dealer_upcard_hidden:
            pl=font_sm.render("👁 透视中",True,C_GREEN2)
            screen.blit(pl,(sx+CARD_W//2-pl.get_width()//2,110+CARD_H+28))

    # 玩家区域
    screen.blit(font_md.render("你的手牌",True,C_GOLD),
                (WIDTH//2-font_md.size("你的手牌")[0]//2,310))
    if solo_hand:
        cw2,sp2=72,12
        if len(solo_hand)>5:
            cw2=max(50,(580-10*(len(solo_hand)-1))//len(solo_hand)); sp2=10
        total_w2=len(solo_hand)*cw2+(len(solo_hand)-1)*sp2
        sx2=WIDTH//2-total_w2//2
        # 正在动画中的牌坐标
        _animating_pos = set()
        for _anim in card_reveal_queue:
            _animating_pos.add((_anim["x"], _anim["y"]))
        for i,c in enumerate(solo_hand):
            _cx = sx2+i*(cw2+sp2); _cy_card = 330
            if (_cx, _cy_card) in _animating_pos:
                continue  # 跳过正在动画的牌，由动画系统绘制
            if is_blinded:
                _back = CARD_BACK_MAP.get(c, my_card_back)
                draw_card(_cx,_cy_card,c,cw2,int(cw2*CARD_H/CARD_W),
                          show_back=True, back_name=_back)
            else:
                draw_card(_cx,_cy_card,c,cw2,int(cw2*CARD_H/CARD_W))
        if is_blinded:
            vt2=font_lg.render("点数: ??? (小丑的戏法)",True,C_GRAY)
            screen.blit(vt2,(WIDTH//2-vt2.get_width()//2,460))
        else:
            val=calc(solo_hand)
            _limit2 = 17 if current_event=="speed" else 21
            vc=C_RED2 if val>_limit2 else (C_GREEN2 if val==_limit2 else C_WHITE)
            screen.blit(font_lg.render(f"点数: {val}",True,vc),
                        (WIDTH//2-font_lg.size(f"点数: {val}")[0]//2,460))

    if solo_state=="betting":
        draw_rect_alpha(screen,C_PANEL,(WIDTH//2-200,490,400,180),235,14)
        pygame.draw.rect(screen,C_GOLD,(WIDTH//2-200,490,400,180),2,border_radius=14)
        screen.blit(font_lg.render("下注",True,C_GOLD),
                    (WIDTH//2-font_lg.size("下注")[0]//2,505))
        screen.blit(font_sm.render(f"筹码: {fmt_chips(money)}  Enter确认",True,C_GRAY),
                    (WIDTH//2-120,538))
        ir=pygame.Rect(WIDTH//2-120,558,240,44)
        pygame.draw.rect(screen,(30,60,40),ir,border_radius=8)
        pygame.draw.rect(screen,C_GOLD,ir,2,border_radius=8)
        screen.blit(font_lg.render(input_text or "100",True,C_WHITE if input_text else C_GRAY),(ir.x+10,ir.y+8))
        for i,qb in enumerate([100,200,500]):
            qr=pygame.Rect(WIDTH//2-155+i*110,612,95,38)
            draw_button(qr,f"+{qb}",C_TABLE2,qr.collidepoint(mx,my_p))
    elif solo_state=="playing" and my_turn:
        btn_map=[("HIT","要牌",C_RED),("STAND","停牌",C_TABLE2),
                 ("DOUBLE","加倍",(120,60,160)),("SPLIT","分牌",(160,100,20)),
                 ("SURRENDER","投降",C_DARKGRAY)]
        btn_defs=[(k,l,c) for k,l,c in btn_map if k in available_opts]
        bw,bh,gap=118,50,10
        total_bw=len(btn_defs)*bw+(len(btn_defs)-1)*gap
        bsx=WIDTH//2-total_bw//2
        for i,(key,label,color) in enumerate(btn_defs):
            r=pygame.Rect(bsx+i*(bw+gap),545,bw,bh)
            draw_button(r,label,color,r.collidepoint(mx,my_p))
        pulse=int(128+127*math.sin(anim_tick*0.08))
        pt=font_lg.render("轮到你了！",True,(pulse,255,pulse))
        screen.blit(pt,(WIDTH//2-pt.get_width()//2,505))
    elif solo_state=="result":
        rc=C_GREEN2 if "赢" in solo_result_msg else (C_GRAY if "平" in solo_result_msg else C_RED2)
        rt=font_xl.render(solo_result_msg,True,rc)
        screen.blit(rt,(WIDTH//2-rt.get_width()//2,500))
        next_btn=pygame.Rect(WIDTH//2-110,555,220,52)
        draw_button(next_btn,"再来一局",C_READY,next_btn.collidepoint(mx,my_p))
    if my_items and solo_state in ("playing", "betting"):
        draw_item_panel()
    return back_btn, shop_btn2, edit_chips_btn, relief_btn2 if 'relief_btn2' in dir() else None

# ===== 主菜单 =====
def draw_main_menu():
    draw_background()
    t="♠ BLACK JACK ♠"
    draw_text_shadow(screen,t,font_xl,C_GOLD,WIDTH//2-font_xl.size(t)[0]//2,60)
    sub=font_md.render("21点对战游戏",True,C_GRAY)
    screen.blit(sub,(WIDTH//2-sub.get_width()//2,112))
    mx,my_p=pygame.mouse.get_pos()
    btns=[(WIDTH//2-200,170,400,72,"人机对局","single_normal",C_TABLE2),
          (WIDTH//2-200,258,400,72,"自定义对局","single_custom",(80,40,120)),
          (WIDTH//2-200,346,400,72,"多人联机","multi",C_READY)]
    for x,y,w,h,label,mode,color in btns:
        r=pygame.Rect(x,y,w,h)
        draw_button(r,label,color,r.collidepoint(mx,my_p))
    return btns

# ===== 多人游戏界面 =====
def draw_game():
    global my_items
    from game_logic import calc
    draw_background()
    draw_rect_alpha(screen,C_PANEL,(0,0,WIDTH,70),200)
    pygame.draw.line(screen,C_GOLD,(0,70),(WIDTH,70),2)
    draw_text_shadow(screen,"BLACK JACK",font_lg,C_GOLD,20,18)
    title_disp=f"[{my_title}] {my_name}" if my_title else my_name
    draw_text_shadow(screen,title_disp,font_md,C_CYAN,200,22)
    draw_text_shadow(screen,f"筹码: {fmt_chips(money)}",font_lg,C_GOLD2,WIDTH//2-80,18)
    if result:
        rc=C_GREEN2 if "赢" in result else (C_GRAY if "平" in result else C_RED2)
        draw_text_shadow(screen,result,font_lg,rc,WIDTH-280,18)
    # 天气/特效状态栏
    _status_items = []
    if blood_moon_active: _status_items.append(("🩸血月", (200,0,0)))
    if tornado_active:    _status_items.append(("🌪️龙卷风", (100,180,255)))
    if silence_field:     _status_items.append(("🤫禁魔", (80,80,160)))
    if doom_beacon_set:   _status_items.append(("🧨信标", (220,60,60)))
    if can_side_bet:      _status_items.append(("🎲可外围", C_GOLD2))
    _sx_off = WIDTH//2 - len(_status_items)*80//2
    for _si,(_stxt,_scol) in enumerate(_status_items):
        _sr = pygame.Rect(_sx_off+_si*84, 75, 80, 26)
        draw_rect_alpha(screen,(0,0,0),(_sr.x,_sr.y,_sr.w,_sr.h),180,6)
        pygame.draw.rect(screen,_scol,_sr,1,border_radius=6)
        screen.blit(font_sm.render(_stxt,True,_scol),(_sr.x+4,_sr.y+5))
    # 西部决斗动画
    if duel_active:
        duel_countdown2 = max(0, duel_countdown)
        prog = 1.0 - duel_countdown2/90.0
        draw_rect_alpha(screen,(0,0,0),(0,0,WIDTH,HEIGHT),180)
        draw_rect_alpha(screen,(60,20,0),(WIDTH//2-250,HEIGHT//2-120,500,240),240,16)
        pygame.draw.rect(screen,(200,150,0),(WIDTH//2-250,HEIGHT//2-120,500,240),2,border_radius=16)
        dt=font_xl.render("⚔️ 西部决斗！",True,(220,180,0))
        screen.blit(dt,(WIDTH//2-dt.get_width()//2,HEIGHT//2-100))
        if duel_countdown2 > 30:
            cnt=str(max(1,int(duel_countdown2/30)))
            pulse=int(128+127*math.sin(anim_tick*0.2))
            ct2=font_xl.render(cnt,True,(pulse,pulse,0))
            screen.blit(ct2,(WIDTH//2-ct2.get_width()//2,HEIGHT//2-30))
        else:
            if duel_my_card:
                draw_card(WIDTH//2-120,HEIGHT//2-40,duel_my_card)
                mt=font_md.render("你的牌",True,C_WHITE)
                screen.blit(mt,(WIDTH//2-120,HEIGHT//2+CARD_H-30))
            if duel_opp_card:
                draw_card(WIDTH//2+20,HEIGHT//2-40,duel_opp_card)
                ot=font_md.render("对手牌",True,C_WHITE)
                screen.blit(ot,(WIDTH//2+20,HEIGHT//2+CARD_H-30))
            if duel_result:
                dr=font_lg.render(duel_result,True,C_GOLD2)
                screen.blit(dr,(WIDTH//2-dr.get_width()//2,HEIGHT//2+CARD_H+10))
        if duel_countdown > 0:
            duel_countdown -= 1
    mx,my_p=pygame.mouse.get_pos()
    # 透视状态
    if paradox_ready:
        pulse=int(128+127*math.sin(anim_tick*0.12))
        bt=font_md.render("时空悖论就绪！点击「再来一次」触发",True,(pulse,pulse,255))
        bw=bt.get_width()+24
        draw_rect_alpha(screen,(60,0,120),(WIDTH//2-bw//2,82,bw,36),230,8)
        screen.blit(bt,(WIDTH//2-bt.get_width()//2,90))
    elif paradox_active:
        pulse=int(128+127*math.sin(anim_tick*0.08))
        bt=font_md.render("时空悖论进行中...命运盲牌结算揭晓",True,(pulse,200,255))
        bw=bt.get_width()+24
        draw_rect_alpha(screen,(40,0,80),(WIDTH//2-bw//2,82,bw,36),220,8)
        screen.blit(bt,(WIDTH//2-bt.get_width()//2,90))
    elif dealer_peek_hand:
        pulse=int(128+127*math.sin(anim_tick*0.08))
        pt2=font_lg.render(f"庄家暗牌: {dealer_peek_hand[0]}",True,(pulse,255,pulse))
        pw2=pt2.get_width()+28
        draw_rect_alpha(screen,(0,80,0),(WIDTH//2-pw2//2,82,pw2,40),230,8)
        pygame.draw.rect(screen,C_GREEN2,(WIDTH//2-pw2//2,82,pw2,40),2,border_radius=8)
        screen.blit(pt2,(WIDTH//2-pt2.get_width()//2,90))
    elif peek_result:
        pulse=int(180+75*math.sin(anim_tick*0.08))
        pt2=font_lg.render(f"庄家暗牌: {peek_result}",True,(pulse,255,pulse))
        pw2=pt2.get_width()+28
        draw_rect_alpha(screen,(0,80,0),(WIDTH//2-pw2//2,82,pw2,40),230,8)
        screen.blit(pt2,(WIDTH//2-pt2.get_width()//2,90))
    # 庄家区域（顶部）
    screen.blit(font_md.render(f"庄家  {banker_name}",True,C_GOLD),(WIDTH//2-80,90))
    if dealer_visible:
        _dw,_dsp=68,10
        _dtw=len(dealer_visible)*_dw+(len(dealer_visible)-1)*_dsp
        _dsx=WIDTH//2-_dtw//2
        for _di,_dc in enumerate(dealer_visible):
            if _di==0 and len(dealer_visible)==1 and not dealer_peek_hand:
                # 只有明牌，暗牌用卡背
                draw_card(_dsx,108,_dc,_dw,int(_dw*CARD_H/CARD_W))
                # 暗牌
                _bk=CARD_BACK_MAP.get(_dc, my_card_back)
                draw_card(_dsx+_dw+_dsp,108,_dc,_dw,int(_dw*CARD_H/CARD_W),show_back=True,back_name=_bk)
            else:
                draw_card(_dsx+_di*(_dw+_dsp),108,_dc,_dw,int(_dw*CARD_H/CARD_W))
        if dealer_peek_hand:
            _pt=font_sm.render("👁 透视中",True,C_GREEN2)
            screen.blit(_pt,(WIDTH//2-_pt.get_width()//2,108+int(68*CARD_H/CARD_W)+6))
    elif banker_name and banker_name!="系统":
        screen.blit(font_sm.render("等待发牌...",True,C_GRAY),(WIDTH//2-50,120))

    # 手牌
    if hand:
        ht=font_md.render("你的手牌",True,C_GOLD)
        screen.blit(ht,(WIDTH//2-ht.get_width()//2,330))
        if len(hand)<=5: cw,ch,sp=CARD_W,CARD_H,14
        else: cw=max(50,(580-10*(len(hand)-1))//len(hand)); ch=int(cw*CARD_H/CARD_W); sp=10
        total_w=len(hand)*cw+(len(hand)-1)*sp
        sx=max(300,(WIDTH-total_w)//2)
        for i,c in enumerate(hand):
            draw_card(sx+i*(cw+sp),355,c,cw,ch)
        val=calc(hand)
        if is_blinded:
            vt=font_lg.render("点数: ???（致盲）",True,C_GRAY)
        else:
            _limit = 17 if current_event=="speed" else 21
            vc=C_RED2 if val>_limit else (C_GREEN2 if val==_limit else C_WHITE)
            vt=font_lg.render(f"点数: {val}",True,vc)
        screen.blit(vt,(WIDTH//2-vt.get_width()//2,490))
    # 多人模式：致盲时手牌显示卡背
    if hand and is_blinded:
        cw_b,sp_b=CARD_W,14
        if len(hand)>5: cw_b=max(50,(580-10*(len(hand)-1))//len(hand)); sp_b=10
        tw_b=len(hand)*cw_b+(len(hand)-1)*sp_b; sx_b=WIDTH//2-tw_b//2
        for i_b,c_b in enumerate(hand):
            _bk_b=CARD_BACK_MAP.get(c_b, my_card_back)
            draw_card(sx_b+i_b*(cw_b+sp_b),355,c_b,cw_b,CARD_H,show_back=True,back_name=_bk_b)
    # 音量按钮由顶层统一绘制
    # 下注阶段
    if bet_mode:
        if bet_submitted:
            # 已下注，显示等待状态（小面板）
            draw_rect_alpha(screen,C_PANEL,(WIDTH//2-200,150,400,80),235,14)
            pygame.draw.rect(screen,C_GOLD,(WIDTH//2-200,150,400,80),2,border_radius=14)
            wt2=font_md.render("✅ 已下注，等待其他玩家...",True,C_GREEN2)
            screen.blit(wt2,(WIDTH//2-wt2.get_width()//2,178))
        else:
            draw_rect_alpha(screen,C_PANEL,(WIDTH//2-200,150,400,220),235,14)
            pygame.draw.rect(screen,C_GOLD,(WIDTH//2-200,150,400,220),2,border_radius=14)
            screen.blit(font_lg.render("下注",True,C_GOLD),(WIDTH//2-font_lg.size("下注")[0]//2,168))
            screen.blit(font_sm.render(f"筹码: {fmt_chips(money)}  Enter确认",True,C_GRAY),
                        (WIDTH//2-120,206))
            ir=pygame.Rect(WIDTH//2-115,228,230,46)
            pygame.draw.rect(screen,(30,60,40),ir,border_radius=8)
            pygame.draw.rect(screen,C_GOLD,ir,2,border_radius=8)
            disp_raw=input_text or "100"
            screen.blit(font_lg.render(disp_raw,True,C_WHITE if input_text else C_GRAY),(ir.x+12,ir.y+9))
            for i,qb in enumerate([100,200,500]):
                qr=pygame.Rect(WIDTH//2-155+i*110,290,95,38)
                draw_button(qr,f"+{qb}",C_TABLE2,qr.collidepoint(mx,my_p))
        # 道具面板（下注前后都显示）
        if my_items:
            draw_item_panel()
        return
    # 操作按钮
    if my_turn and available_opts:
        btn_map=[("HIT","要牌",C_RED),("STAND","停牌",C_TABLE2),
                 ("DOUBLE","加倍",(120,60,160)),("SPLIT","分牌",(160,100,20)),
                 ("SURRENDER","投降",C_DARKGRAY)]
        btn_defs=[(k,l,c) for k,l,c in btn_map if k in available_opts]
        bw,bh,gap=118,50,10
        total_bw=len(btn_defs)*bw+(len(btn_defs)-1)*gap
        bsx=WIDTH//2-total_bw//2
        for i,(key,label,color) in enumerate(btn_defs):
            r=pygame.Rect(bsx+i*(bw+gap),550,bw,bh)
            draw_button(r,label,color,r.collidepoint(mx,my_p))
        pulse=int(128+127*math.sin(anim_tick*0.08))
        pt=font_lg.render("轮到你了！",True,(pulse,255,pulse))
        screen.blit(pt,(WIDTH//2-pt.get_width()//2,512))
    elif my_turn:
        hr=pygame.Rect(WIDTH//2-140,550,120,50)
        sr=pygame.Rect(WIDTH//2+20,550,120,50)
        draw_button(hr,"要牌",C_RED,hr.collidepoint(mx,my_p))
        draw_button(sr,"停牌",C_TABLE2,sr.collidepoint(mx,my_p))
        pulse=int(128+127*math.sin(anim_tick*0.08))
        pt=font_lg.render("轮到你了！",True,(pulse,255,pulse))
        screen.blit(pt,(WIDTH//2-pt.get_width()//2,512))
    else:
        if waiting_for:
            pulse=int(160+95*math.sin(anim_tick*0.05))
            wt=font_md.render(f"等待 {waiting_for} 操作...",True,(pulse,pulse,80))
        else:
            wt=font_md.render("等待其他玩家操作...",True,C_GRAY)
        screen.blit(wt,(WIDTH//2-wt.get_width()//2,530))
        # 外围下注按钮（停牌/爆牌后可用）
        if can_side_bet:
            sb_btn=pygame.Rect(WIDTH//2-100,570,200,42)
            draw_button(sb_btn,"🎲 外围下注",( 100,60,20),sb_btn.collidepoint(mx,my_p))
    # 道具面板（过滤已在 draw_item_panel 和 _get_item_rects 里统一处理）
    draw_item_panel()
    # 商店按钮（下注/结算时显示）
    # 商店按钮始终显示
    shop_btn_g=pygame.Rect(15,78,120,34)
    draw_button(shop_btn_g,"商店",C_TABLE2,shop_btn_g.collidepoint(mx,my_p))

# ===== 主循环 =====
def main():
    global my_turn,bet_mode,is_ready,anim_tick,input_text,screen_state
    global fi_name,fi_ip,fi_focus,show_edit,edit_name,edit_ip,edit_focus
    global my_name,server_ip,grabbing_done,insurance_done,available_opts
    global banker_name,is_banker,relief_available,is_spectating,spectator_count
    global screen_shop,shop_tab,shop_scroll,show_title_menu
    global my_items,item_used,peek_result,my_card_back,my_tablecloth
    global my_owned_backs,my_owned_cloths,my_achievements,my_title
    global bounty_name,current_event,event_name,new_achievements,ach_popup_tick
    global money,hand,result,result_gain,log,waiting_for,in_lobby
    global total_players,ready_players,countdown,game_started
    global game_mode,solo_state,solo_hand,solo_dealer_hand,solo_bet
    global solo_deck,solo_result_msg,solo_dealer_upcard_hidden
    global leaderboard_data,show_leaderboard
    global show_item_panel,solo_submode,editing_chips,edit_chips_input
    global is_blinded,paradox_ready,paradox_active,game_phase
    global active_used_count,passive_used_count,dealer_peek_hand
    global log_scroll,log_visible,connected,connect_status,connect_fail_tick,client,current_game_id,lucky_buff_active,lucky_buff_games,silence_field,doom_beacon_set,blood_moon_active,tornado_active,can_side_bet,side_bet_mode,duel_active,duel_countdown,duel_my_card,duel_opp_card,duel_result,bet_submitted,dealer_visible,dealer_upcard_str,event_announce_tick,target_select_mode,target_select_item,prep_active,prep_passive,prep_confirmed,shop_opened_gid,prep_start_time,prep_scroll,shop_open_token,_prev_screen_shop

    connected = False
    load_images()
    global CARD_BACK_MAP
    CARD_BACK_MAP = _build_card_back_map()

    saved_name,saved_ip=load_profile()
    if saved_name: fi_name=saved_name
    if saved_ip:   fi_ip=saved_ip

    running=True
    clock=pygame.time.Clock()

    while running:
        anim_tick+=1
        update_particles()

        for e in pygame.event.get():
            if e.type==pygame.QUIT:
                running=False
            # 目标选择弹窗事件（最高优先级，拦截所有点击）
            if target_select_mode and e.type==pygame.MOUSEBUTTONDOWN and e.button==1:
                _tbtns2,_tcr2 = draw_target_select()
                _hit2 = False
                for _tr2,_tname2 in _tbtns2:
                    if _tr2.collidepoint(e.pos):
                        target_select_mode=False
                        if screen_state=="game":
                            client.send(f"[USE_ITEM]{target_select_item}|{_tname2}\n".encode())
                            log.append(f"对 {_tname2} 使用了 {target_select_item}")
                            item_used[target_select_item]=True
                            from items import PASSIVE_ITEMS as _PIx2
                            if target_select_item in _PIx2: passive_used_count+=1
                            else: active_used_count+=1
                            try: Shop.use_item(my_name,target_select_item)
                            except: pass
                            _load_player_cosmetics(my_name)
                            show_item_panel=False
                        _hit2=True; break
                if not _hit2 and _tcr2.collidepoint(e.pos):
                    target_select_mode=False
                continue  # 弹窗打开时拦截所有其他事件
            # 音量按钮（所有界面，事件驱动）
            if e.type==pygame.MOUSEBUTTONDOWN and e.button==1:
                _vol_r2 = pygame.Rect(WIDTH-115, 8, 104, 28)
                if _vol_r2.collidepoint(e.pos):
                    try:
                        _v2 = round(pygame.mixer.music.get_volume(), 2)
                        _steps2 = [0.0, 0.15, 0.25, 0.35, 0.50, 0.75, 1.0]
                        _closest2 = min(_steps2, key=lambda x: abs(x-_v2))
                        _idx2 = _steps2.index(_closest2)
                        pygame.mixer.music.set_volume(_steps2[(_idx2+1) % len(_steps2)])
                    except: pass

            # 改筹码弹窗（最高优先级）
            if editing_chips:
                pw,ph=400,180; px,py=WIDTH//2-pw//2,HEIGHT//2-ph//2
                ok_r=pygame.Rect(px+pw//2-110,py+138,100,36)
                ca_r=pygame.Rect(px+pw//2+10,py+138,100,36)
                if e.type==pygame.KEYDOWN:
                    if e.key==pygame.K_RETURN:
                        new_chips=parse_bet_input(edit_chips_input)
                        if new_chips>0:
                            money=new_chips; save_record_solo(my_name,money)
                            log.append(f"筹码设为 {fmt_chips(money)}")
                        editing_chips=False; edit_chips_input=""
                    elif e.key==pygame.K_ESCAPE:
                        editing_chips=False; edit_chips_input=""
                    elif e.key==pygame.K_BACKSPACE:
                        edit_chips_input=edit_chips_input[:-1]
                elif e.type==pygame.TEXTINPUT:
                    if len(edit_chips_input)<15: edit_chips_input+=e.text
                elif e.type==pygame.MOUSEBUTTONDOWN:
                    if ok_r.collidepoint(e.pos):
                        new_chips=parse_bet_input(edit_chips_input)
                        if new_chips>0:
                            money=new_chips; save_record_solo(my_name,money)
                            log.append(f"筹码设为 {fmt_chips(money)}")
                        editing_chips=False; edit_chips_input=""
                    elif ca_r.collidepoint(e.pos):
                        editing_chips=False; edit_chips_input=""
                continue

            # Tab键切换日志
            if e.type==pygame.KEYDOWN and e.key==pygame.K_TAB:
                log_visible=not log_visible

            # 日志窗口关闭/滚轮
            if log_visible:
                if e.type==pygame.MOUSEWHEEL:
                    log_scroll=max(0,log_scroll-e.y)
                elif e.type==pygame.MOUSEBUTTONDOWN:
                    PW2,PH2=760,480; PX2,PY2=WIDTH//2-PW2//2,HEIGHT//2-PH2//2
                    cr2=pygame.Rect(PX2+PW2-60,PY2+8,50,40)
                    if cr2.collidepoint(e.pos): log_visible=False
                continue  # 日志打开时拦截所有事件

            # 商店覆盖层（打开时拦截所有事件）
            if screen_shop:
                if e.type==pygame.MOUSEWHEEL:
                    shop_scroll=max(0,shop_scroll-e.y*30)
                elif e.type==pygame.MOUSEBUTTONDOWN:
                    PW,PH=820,560; PX,PY=WIDTH//2-PW//2,HEIGHT//2-PH//2
                    close_r=pygame.Rect(PX+PW-60,PY+8,50,40)
                    tabs=[("items","道具"),("cardbacks","卡背"),("tablecloth","桌布"),("achievements","成就")]
                    tab_w=PW//len(tabs)
                    for i,(key,_) in enumerate(tabs):
                        tr=pygame.Rect(PX+i*tab_w,PY+58,tab_w,36)
                        if tr.collidepoint(e.pos): shop_tab=key; shop_scroll=0; break
                    if close_r.collidepoint(e.pos):
                        screen_shop=False; _reload_cosmetics()
                    else:
                        sn=_shop_name()
                        if shop_tab=="items":
                            is_custom2 = sn.startswith("__custom__")
                            gid = None if is_custom2 else _shop_game_id()
                            if is_custom2:
                                personal2 = {}
                                items_list2 = list(ITEMS.items())
                            else:
                                personal2 = getattr(Shop,"get_personal_shop",lambda a,b,c:{"命运盲盒":{"price":300,"qty":99}})(sn, gid, money)
                                items_list2 = []
                                if "命运盲盒" in ITEMS:
                                    items_list2.append(("命运盲盒", ITEMS["命运盲盒"]))
                                for _in2 in personal2:
                                    if _in2 != "命运盲盒" and _in2 in ITEMS and int(personal2.get(_in2,{}).get("qty",0)) > 0:
                                        items_list2.append((_in2, ITEMS[_in2]))
                            y=PY+100-shop_scroll
                            for iname,item in items_list2:
                                buy_r=pygame.Rect(PX+PW-140,y+16,120,36)
                                price2 = item['price'] if is_custom2 else int(personal2.get(iname,{}).get("price", ITEMS.get(iname,{}).get("price",999)))
                                cd2   = 0 if is_custom2 else getattr(Shop,"get_item_cooldown",lambda a,b:0)(sn,iname)
                                if buy_r.collidepoint(e.pos) and money>=price2 and cd2==0:
                                    Shop.save_player_data(sn,{},chips=money)
                                    ok2,msg2=Shop.buy_item(sn,iname,game_id=gid,chips_override=money)
                                    if ok2:
                                        try:
                                            money = Shop.get_player_data(sn)["chips"]
                                        except:
                                            money -= price2
                                        # 多人联机：把购买后的筹码同步给服务器
                                        try:
                                            if connected and client and screen_state in ("prep","game"):
                                                client.send(f"[SYNC_MONEY]{money}\n".encode())
                                        except:
                                            pass
                                        if msg2.startswith("opened:"):
                                            _handle_blindbox_result(msg2[7:], sn)
                                            log_visible=True; log_scroll=0
                                        else:
                                            log.append(f"购买了 {iname}，花费{price2}")
                                        _reload_cosmetics()
                                    else:
                                        log.append(f"购买失败: {msg2}")
                                y+=78
                        elif shop_tab=="cardbacks":
                            y=PY+100-shop_scroll
                            for bname,bdata in CARD_BACKS.items():
                                owned=bname in my_owned_backs
                                if owned:
                                    eq_r=pygame.Rect(PX+PW-130,y+18,110,35)
                                    if eq_r.collidepoint(e.pos):
                                        Shop.equip_card_back(sn,bname); _reload_cosmetics()
                                else:
                                    buy_r=pygame.Rect(PX+PW-130,y+18,110,35)
                                    if buy_r.collidepoint(e.pos) and money>=bdata['price']:
                                        Shop.save_player_data(sn,{},chips=money)
                                        ok2,_=Shop.buy_card_back(sn,bname)
                                        if ok2: money-=bdata['price']; _reload_cosmetics()
                                y+=80
                        elif shop_tab=="tablecloth":
                            y=PY+100-shop_scroll
                            for tname,tdata in TABLECLOTHS.items():
                                owned=tname in my_owned_cloths
                                if owned:
                                    eq_r=pygame.Rect(PX+PW-130,y+14,110,34)
                                    if eq_r.collidepoint(e.pos):
                                        Shop.equip_tablecloth(sn,tname); _reload_cosmetics()
                                else:
                                    buy_r=pygame.Rect(PX+PW-130,y+14,110,34)
                                    if buy_r.collidepoint(e.pos) and (money>=tdata['price'] or tdata['price']==0):
                                        if tdata['price']==0:
                                            Shop.equip_tablecloth(sn,tname); _reload_cosmetics()
                                        else:
                                            Shop.save_player_data(sn,{},chips=money)
                                            ok2,_=Shop.buy_tablecloth(sn,tname)
                                            if ok2: money-=tdata['price']; _reload_cosmetics()
                                y+=72
                continue  # 商店打开时，所有事件处理完后跳过游戏逻辑

            # 主菜单
            if screen_state=="menu":
                if e.type==pygame.MOUSEBUTTONDOWN:
                    normal_btn=pygame.Rect(WIDTH//2-200,170,400,72)
                    custom_btn=pygame.Rect(WIDTH//2-200,258,400,72)
                    multi_btn =pygame.Rect(WIDTH//2-200,346,400,72)
                    def _enter_solo(submode):
                        global game_mode,solo_submode,my_name,money,screen_state
                        game_mode="single_"+submode; solo_submode=submode
                        name=fi_name.strip()
                        if not name: screen_state="name_input"; return
                        my_name=name
                        if submode=="normal":
                            _load_player_cosmetics(my_name)
                            _data = load_save()
                            _players = _data.get("players", {})
                            if my_name in _players:
                                # 有存档记录，直接用（哪怕是0）
                                money = _players[my_name]
                            else:
                                # 第一次玩，给初始筹码
                                money = BONUS_PER_SESSION
                                save_record(my_name, money)
                        else:
                            _load_player_cosmetics_custom(my_name); money=get_custom_chips(my_name)
                        screen_state="solo"; solo_new_game(); play_bgm("game")
                    if normal_btn.collidepoint(e.pos):  _enter_solo("normal")
                    elif custom_btn.collidepoint(e.pos): _enter_solo("custom")
                    elif multi_btn.collidepoint(e.pos):
                        game_mode="multi"; screen_state="name_input"

            # 名称输入
            elif screen_state=="name_input":
                if e.type==pygame.KEYDOWN:
                    if e.key==pygame.K_TAB:
                        fi_focus="ip" if fi_focus=="name" else "name"
                    elif e.key==pygame.K_RETURN:
                        if fi_name.strip() and fi_ip.strip() and connect_status=="":
                            do_connect(fi_name.strip(), fi_ip.strip())
                    elif e.key==pygame.K_BACKSPACE:
                        if fi_focus=="name": fi_name=fi_name[:-1]
                        else: fi_ip=fi_ip[:-1]
                elif e.type==pygame.TEXTINPUT:
                    if fi_focus=="name" and len(fi_name)<12: fi_name+=e.text
                    elif fi_focus=="ip" and len(fi_ip)<20: fi_ip+=e.text
                elif e.type==pygame.MOUSEBUTTONDOWN:
                    pw,ph=540,380; px,py=WIDTH//2-pw//2,130
                    name_rect=pygame.Rect(px+30,py+186,pw-60,44)
                    ip_rect  =pygame.Rect(px+30,py+270,pw-60,44)
                    ok_btn   =pygame.Rect(WIDTH//2-110,py+350,220,52)
                    if name_rect.collidepoint(e.pos): fi_focus="name"
                    elif ip_rect.collidepoint(e.pos): fi_focus="ip"
                    elif ok_btn.collidepoint(e.pos) and fi_name.strip() and fi_ip.strip() and connect_status=="":
                        do_connect(fi_name.strip(), fi_ip.strip())

            # 修改信息弹窗
            if show_edit:
                if e.type==pygame.KEYDOWN:
                    if e.key==pygame.K_TAB: edit_focus="ip" if edit_focus=="name" else "name"
                    elif e.key==pygame.K_ESCAPE: show_edit=False
                    elif e.key==pygame.K_BACKSPACE:
                        if edit_focus=="name": edit_name=edit_name[:-1]
                        else: edit_ip=edit_ip[:-1]
                elif e.type==pygame.TEXTINPUT:
                    if edit_focus=="name" and len(edit_name)<12: edit_name+=e.text
                    elif edit_focus=="ip" and len(edit_ip)<20: edit_ip+=e.text
                if e.type==pygame.MOUSEBUTTONDOWN:
                    ok,ca,nr2,ir2=draw_edit_popup()
                    if ok.collidepoint(e.pos) and edit_name.strip() and edit_ip.strip():
                        my_name=edit_name.strip(); server_ip=edit_ip.strip()
                        save_profile(my_name,server_ip); show_edit=False
                    elif ca.collidepoint(e.pos): show_edit=False
                    elif nr2.collidepoint(e.pos): edit_focus="name"
                    elif ir2.collidepoint(e.pos): edit_focus="ip"

            # 大厅
            elif screen_state=="lobby":
                if e.type==pygame.MOUSEBUTTONDOWN:
                    # 固定rect
                    ready_btn  = pygame.Rect(WIDTH//2-110,390,220,52)
                    edit_btn   = pygame.Rect(WIDTH-175,HEIGHT-55,160,42)
                    shop_btn_l = pygame.Rect(WIDTH-175,HEIGHT-105,160,42)
                    lb_btn     = pygame.Rect(WIDTH-175,HEIGHT-155,160,42)
                    bmb        = pygame.Rect(15,15,140,38)
                    relief_btn = pygame.Rect(WIDTH-175,HEIGHT-205,160,42) if money<100 else None
                    if ready_btn.collidepoint(e.pos):
                        is_ready=not is_ready
                        try:
                            client.send(b"[READY]\n" if is_ready else b"[UNREADY]\n")
                            add_particles(e.pos[0],e.pos[1],C_GOLD2 if is_ready else C_RED2,15)
                        except Exception as _re:
                            log.append(f"发送失败: {_re}")
                            is_ready = not is_ready  # 回滚
                    elif edit_btn.collidepoint(e.pos):
                        edit_name=my_name; edit_ip=server_ip; edit_focus="name"; show_edit=True
                    elif relief_btn and relief_btn.collidepoint(e.pos):
                        client.send(b"[RELIEF]\n")
                    elif shop_btn_l.collidepoint(e.pos):
                        screen_shop=True; shop_tab="items"; shop_scroll=0; _reload_cosmetics()
                        shop_opened_gid = _shop_game_id()
                    elif lb_btn.collidepoint(e.pos):
                        show_leaderboard=not show_leaderboard
                    elif bmb.collidepoint(e.pos):
                        screen_state="menu"; connected=False; is_ready=False
                        try: client.close()
                        except: pass
                        import socket as _s; client=_s.socket()

            # 抢庄
            elif screen_state=="grabbing":
                if e.type==pygame.MOUSEBUTTONDOWN:
                    gb,ngb=draw_grabbing()
                    if gb and gb.collidepoint(e.pos):
                        client.send(b"[GRAB]1\n"); grabbing_done=True
                    elif ngb and ngb.collidepoint(e.pos):
                        client.send(b"[GRAB]0\n"); grabbing_done=True

            elif screen_state=="prep":
                if e.type==pygame.MOUSEWHEEL:
                    prep_scroll = max(0, prep_scroll - e.y * 30)
                if e.type==pygame.MOUSEBUTTONDOWN:
                    ok_r2,skip_r2,act_rs,pas_rs = draw_prep_phase()
                    # 选择主动道具
                    for r2,nm2 in act_rs:
                        if r2.collidepoint(e.pos):
                            prep_active = ("" if prep_active==nm2 else nm2)
                    # 选择被动道具
                    for r2,nm2 in pas_rs:
                        if r2.collidepoint(e.pos):
                            prep_passive = ("" if prep_passive==nm2 else nm2)
                    # 确认
                    if ok_r2.collidepoint(e.pos) or skip_r2.collidepoint(e.pos):
                        # 把未选择的道具从本局携带中移除（存入临时携带列表）
                        # 这里只记录选择，实际道具仍在 my_items
                        # server_side: game使用时检查 prep_active/prep_passive
                        screen_state="game"
                        prep_confirmed=True; bet_submitted=False; prep_scroll=0
                        log.append(f"✅ 携带: 主动={prep_active or '无'} 被动={prep_passive or '无'}")
                        try:
                            client.send(b"[PREP_DONE]\n")
                            client.send(f"[EQUIPPED]{prep_active}|{prep_passive}\n".encode())
                        except: pass

            # 保险
            elif screen_state=="insurance":
                if e.type==pygame.MOUSEBUTTONDOWN:
                    buy_btn2,no_btn2=draw_insurance()
                    if buy_btn2 and buy_btn2.collidepoint(e.pos):
                        client.send(b"[INSURANCE]1\n"); insurance_done=True
                    elif no_btn2 and no_btn2.collidepoint(e.pos):
                        client.send(b"[INSURANCE]0\n"); insurance_done=True

            # 单人游戏
            elif screen_state=="solo":
                if e.type==pygame.MOUSEWHEEL:
                    pass  # 日志已在顶部处理
                if e.type==pygame.KEYDOWN:
                    if solo_state=="betting":
                        if e.key==pygame.K_RETURN:
                            bet_val=parse_bet_input(input_text) if input_text else 100
                            bet_val=max(1,min(bet_val or 100,money))
                            if money>0 and bet_val>0:
                                solo_bet=bet_val; money-=solo_bet; input_text=""
                                save_record_solo(my_name, money)  # 下注立即存档防止逃跑
                                solo_deal()
                        elif e.key==pygame.K_BACKSPACE: input_text=input_text[:-1]
                    elif solo_state=="playing" and my_turn:
                        if e.key==pygame.K_h: solo_hit()
                        elif e.key==pygame.K_s: solo_stand()
                elif e.type==pygame.TEXTINPUT:
                    if solo_state=="betting" and e.text.isdigit() and len(input_text)<10:
                        new_val=input_text+e.text
                        parsed=parse_bet_input(new_val)
                        if parsed and parsed>money: input_text=str(money)
                        else: input_text=new_val
                if e.type==pygame.MOUSEBUTTONDOWN:
                    back_btn2    = pygame.Rect(WIDTH-160, 78, 140, 34)
                    shop_btn3    = pygame.Rect(WIDTH-310, 78, 140, 34)
                    ecs_btn      = pygame.Rect(WIDTH-460, 78, 140, 34)
                    relief_btn3  = pygame.Rect(15, 78, 180, 34)
                    if back_btn2.collidepoint(e.pos):
                        # 返回前强制结算当前局损失
                        if solo_state == "playing":
                            # 正在对局中退出，视为投降：损失下注筹码
                            if solo_bet > 0:
                                log.append(f"⚠ 中途退出，损失下注 {fmt_chips(solo_bet)} 筹码")
                                save_record_solo(my_name, money)  # money 已在下注时扣除
                        elif solo_state == "result":
                            # 结算界面退出，已结算无需额外处理
                            pass
                        screen_state="menu"; play_bgm("lobby"); connected=False
                    elif shop_btn3.collidepoint(e.pos) and solo_state in ("betting","idle","result"):
                        screen_shop=True; shop_tab="items"; shop_scroll=0; _reload_cosmetics()
                    elif ecs_btn.collidepoint(e.pos) and solo_submode=="custom" and solo_state in ("betting","result"):
                        editing_chips=True; edit_chips_input=str(money)
                    elif (relief_btn3.collidepoint(e.pos) and solo_submode=="normal"
                          and money<100 and solo_state in ("betting","result","idle")):
                        amt, msg2 = get_solo_relief(my_name)
                        if amt > 0:
                            money += amt
                            save_record(my_name, money)
                            log.append(f"💰 {msg2}")
                            add_particles(e.pos[0],e.pos[1],C_GOLD2,20)
                        else:
                            log.append(f"❌ {msg2}")
                    elif solo_state=="betting":
                        for i,qb in enumerate([100,200,500]):
                            qr=pygame.Rect(WIDTH//2-155+i*110,612,95,38)
                            if qr.collidepoint(e.pos):
                                cur=parse_bet_input(input_text) if input_text else 0
                                input_text=str(min(cur+qb,money))
                    elif solo_state=="playing" and my_turn:
                        btn_map=[("HIT","要牌",C_RED),("STAND","停牌",C_TABLE2),
                                 ("DOUBLE","加倍",(120,60,160)),("SPLIT","分牌",(160,100,20)),
                                 ("SURRENDER","投降",C_DARKGRAY)]
                        btn_defs=[(k,l,c) for k,l,c in btn_map if k in available_opts]
                        bw,bh,gap=118,50,10
                        total_bw=len(btn_defs)*bw+(len(btn_defs)-1)*gap
                        bsx=WIDTH//2-total_bw//2
                        for i,(key,label,color) in enumerate(btn_defs):
                            r=pygame.Rect(bsx+i*(bw+gap),545,bw,bh)
                            if r.collidepoint(e.pos):
                                if key=="HIT": solo_hit()
                                elif key=="STAND": solo_stand()
                                elif key=="DOUBLE": solo_double()
                                elif key=="SURRENDER": solo_surrender()
                                elif key=="SPLIT":
                                    from game_logic import calc as _gc
                                    money-=solo_bet; solo_hand.append(solo_deck.pop())
                                    _solo_update_opts()
                                break
                    elif solo_state=="result":
                        next_r=pygame.Rect(WIDTH//2-110,555,220,52)
                        if next_r.collidepoint(e.pos): solo_new_game(); input_text=""
                    # 道具面板
                    main_ibtn2,item_btns3=_get_item_rects()
                    if main_ibtn2 and main_ibtn2.collidepoint(e.pos):
                        show_item_panel=not show_item_panel
                    elif show_item_panel:
                        for _ib,_iname,_used,_passive,_pok in item_btns3:
                            if not _ib.collidepoint(e.pos): continue
                            if _used or _passive: break
                            item_used[_iname]=True
                            from items import PASSIVE_ITEMS as _PIu2
                            if _iname in _PIu2: passive_used_count+=1
                            else: active_used_count+=1
                            _sn=_solo_shop_name()
                            Shop.use_item(_sn,_iname)
                            if solo_submode=="normal":
                                try: getattr(Shop,"set_item_cooldown",lambda a,b,c:None)(_sn,_iname,2)
                                except: pass
                            _reload_cosmetics()
                            log.append(f"使用了 {ITEMS.get(_iname,{}).get('emoji','')} {_iname}")
                            add_particles(e.pos[0],e.pos[1],ITEMS.get(_iname,{}).get("color",(200,180,0)),15)
                            if _iname=="透视眼镜":
                                if solo_dealer_hand:
                                    dealer_peek_hand=list(solo_dealer_hand); peek_result=str(solo_dealer_hand[0])
                                    log.append(f"庄家暗牌: {solo_dealer_hand[0]}"); log_visible=True; log_scroll=0
                                else: log.append("请在发牌后使用透视眼镜")
                            elif _iname=="搏命契约": log.append("搏命契约激活！胜负x3.5")
                            elif _iname=="强买强卖":
                                if solo_deck and solo_dealer_hand:
                                    from game_logic import calc as _gc0
                                    _c0=solo_deck.pop(); solo_dealer_hand.append(_c0)
                                    log.append(f"庄家被迫摸牌 {_c0} -> {_gc0(solo_dealer_hand)}点")
                                else: log.append("请在发牌后使用")
                            elif _iname=="再来一次":
                                if item_used.get("时光倒流"):
                                    log.append("时空悖论触发！盲抽命运之牌...")
                                    if solo_deck:
                                        from game_logic import calc as _gc1
                                        _blind=solo_deck.pop(); solo_hand.append(_blind); _bv=_gc1(solo_hand)
                                        log.append(f"盲牌揭晓: {_blind}  点数:{_bv}")
                                        if _bv>21: log.append("时空惩罚！双倍扣注"); money-=solo_bet; solo_result_msg="时空悖论！双倍扣注"; solo_end_round()
                                        else: solo_dealer_turn()
                                else:
                                    if solo_deck:
                                        from game_logic import calc as _gc4
                                        _c4=solo_deck.pop(); solo_hand.append(_c4); _v4=_gc4(solo_hand)
                                        log.append(f"再来一次：摸了 {_c4} -> {_v4}点")
                                        if _v4>21: solo_result_msg="再来一次后爆牌"; solo_end_round()
                                        else: available_opts=["HIT","STAND"]
                            elif _iname=="命运盲盒":
                                # 单人模式开箱
                                _sn2=_solo_shop_name()
                                _res=getattr(Shop,"_open_blind_box",lambda a,b:"nothing:无效")(_sn2, current_game_id)
                                _handle_blindbox_result(_res, _sn2)
                            elif _iname=="致盲烟雾": log.append("单人模式：致盲对AI无效")
                            elif _iname in ("移花接木","灵魂链接"): log.append(f"{_iname}：单人模式暂不支持")
                            show_item_panel=False; break

            # 多人游戏
            elif screen_state=="game":
                if e.type==pygame.MOUSEBUTTONDOWN:
                    # 音量
                    # 音量由顶层统一处理
                    # 商店按钮（任何时候都可点）
                    shop_btn_g2=pygame.Rect(15,78,120,34)
                    if shop_btn_g2.collidepoint(e.pos):
                        screen_shop=True; shop_tab="items"; shop_scroll=0; _reload_cosmetics()
                    elif bet_mode and not bet_submitted:
                        for i,qb in enumerate([100,200,500]):
                            qr=pygame.Rect(WIDTH//2-155+i*110,290,95,38)
                            if qr.collidepoint(e.pos):
                                cur=parse_bet_input(input_text) if input_text else 0
                                new_val=str(min(cur+qb,money)); input_text=new_val
                    elif bet_mode:
                        if not bet_submitted:
                            for i,qb in enumerate([100,200,500]):
                                qr=pygame.Rect(WIDTH//2-155+i*110,290,95,38)
                                if qr.collidepoint(e.pos):
                                    cur=parse_bet_input(input_text) if input_text else 0
                                    new_val=str(min(cur+qb,money)); input_text=new_val
                    elif my_turn and available_opts:
                        btn_map=[("HIT","要牌",C_RED),("STAND","停牌",C_TABLE2),
                                 ("DOUBLE","加倍",(120,60,160)),("SPLIT","分牌",(160,100,20)),
                                 ("SURRENDER","投降",C_DARKGRAY)]
                        btn_defs=[(k,l,c) for k,l,c in btn_map if k in available_opts]
                        bw,bh,gap=118,50,10
                        total_bw=len(btn_defs)*bw+(len(btn_defs)-1)*gap
                        bsx=WIDTH//2-total_bw//2
                        for i,(key,label,color) in enumerate(btn_defs):
                            r=pygame.Rect(bsx+i*(bw+gap),550,bw,bh)
                            if r.collidepoint(e.pos):
                                client.send(f"[ACTION]{key}\n".encode())
                                my_turn=False; available_opts=[]
                                add_particles(e.pos[0],e.pos[1],C_GREEN2,8)
                                break
                    elif my_turn:
                        hr=pygame.Rect(WIDTH//2-140,550,120,50)
                        sr=pygame.Rect(WIDTH//2+20,550,120,50)
                        if hr.collidepoint(e.pos):
                            client.send(b"[ACTION]HIT\n"); my_turn=False
                        elif sr.collidepoint(e.pos):
                            client.send(b"[ACTION]STAND\n"); my_turn=False
                    elif can_side_bet:
                        sb_btn2=pygame.Rect(WIDTH//2-100,570,200,42)
                        if sb_btn2.collidepoint(e.pos):
                            side_bet_mode=True; side_bet_target=""; side_bet_type=""; side_bet_input=""
                    # 道具面板（独立检查，不受 elif 链影响）
                if e.type==pygame.MOUSEBUTTONDOWN and my_items and screen_state=="game":
                    main_ibtn,item_btns2=_get_item_rects()
                    if main_ibtn and main_ibtn.collidepoint(e.pos):
                        show_item_panel=not show_item_panel
                    elif show_item_panel:
                        _NEED_TARGET = {"强买强卖","致盲烟雾","移花接木","第三只手","吸血印记","狸猫换太子"}
                        for ib,iname,used,passive,phase_ok in item_btns2:
                            if ib.collidepoint(e.pos) and not used and not passive and phase_ok:
                                if iname in _NEED_TARGET:
                                    # 需要目标：弹出选择弹窗
                                    target_select_mode=True; target_select_item=iname
                                    show_item_panel=False
                                else:
                                    item_used[iname]=True
                                    from items import PASSIVE_ITEMS as _PIu
                                    if iname in _PIu: passive_used_count+=1
                                    else: active_used_count+=1
                                    client.send(f"[USE_ITEM]{iname}\n".encode())
                                    log.append(f"使用了 {iname}，等待响应...")
                                    Shop.use_item(my_name,iname)
                                    _load_player_cosmetics(my_name)
                                    add_particles(e.pos[0],e.pos[1],ITEMS.get(iname,{}).get("color",(212,175,55)),15)
                                    show_item_panel=False; log_visible=True; log_scroll=0
                                break
                if e.type==pygame.KEYDOWN and bet_mode:
                    if e.key==pygame.K_RETURN:
                        bet_val=parse_bet_input(input_text) if input_text else 100
                        bet_val=max(1,min(bet_val or 100,money))
                        client.send(f"[BET]{bet_val}\n".encode())
                        input_text=""
                        # 不关闭 bet_mode，等收到 [HAND] 时才切换
                        # 改为显示等待状态
                        bet_submitted = True
                    elif e.key==pygame.K_BACKSPACE: input_text=input_text[:-1]
                elif e.type==pygame.TEXTINPUT and bet_mode:
                    new_val=input_text+e.text
                    parsed=parse_bet_input(new_val) if new_val else 0
                    if parsed and parsed>money: input_text=str(money)
                    else: input_text=new_val

        # ===== 绘制 =====
        if screen_state=="menu":
            play_bgm("lobby"); draw_main_menu()
        elif screen_state=="solo":
            if bet_mode: play_bgm("betting")
            elif solo_result_msg: play_bgm("result")
            else: play_bgm("game")
            draw_solo_game()
            if editing_chips: draw_chips_edit_popup()
        elif screen_state=="name_input":
            play_bgm("lobby"); draw_name_input()
            # 连接状态提示
            if connect_status == "connecting":
                pulse = int(128+127*math.sin(anim_tick*0.1))
                ct = font_lg.render("正在连接...", True, (pulse,255,pulse))
                draw_rect_alpha(screen, (0,0,0), (WIDTH//2-ct.get_width()//2-16,HEIGHT//2-24,ct.get_width()+32,50), 200, 10)
                screen.blit(ct, (WIDTH//2-ct.get_width()//2, HEIGHT//2-14))
            elif connect_status.startswith("fail:"):
                err = connect_status[5:]
                et = font_md.render(f"连接失败: {err}", True, C_RED2)
                draw_rect_alpha(screen,(0,0,0),(WIDTH//2-et.get_width()//2-10,HEIGHT-70,et.get_width()+20,40),180,8)
                screen.blit(et, (WIDTH//2-et.get_width()//2, HEIGHT-60))
                if connect_fail_tick == 0: connect_fail_tick = anim_tick
                if anim_tick - connect_fail_tick > 180:  # 3秒后清除
                    connect_status = ""; connect_fail_tick = 0
            elif connect_status == "ok":
                add_particles(WIDTH//2, HEIGHT//2, C_GOLD2, 20)
                connect_status = ""
                # screen_state 已由子线程设为 lobby，下帧自动切换
        elif screen_state=="lobby":
            play_bgm("lobby"); draw_lobby()
            if show_edit: draw_edit_popup()
            if show_leaderboard:
                cr3=draw_leaderboard()
                if pygame.mouse.get_pressed()[0] and cr3.collidepoint(pygame.mouse.get_pos()):
                    show_leaderboard=False
        elif screen_state=="grabbing":
            play_bgm("grabbing"); draw_grabbing()
        elif screen_state=="prep":
            play_bgm("grabbing"); draw_prep_phase()
        elif screen_state=="spectating":
            play_bgm("lobby"); draw_spectating()
        elif screen_state=="insurance":
            play_bgm("game"); draw_insurance()
        elif screen_state=="game":
            if bet_mode: play_bgm("betting")
            elif result: play_bgm("result")
            else: play_bgm("game")
            draw_game()
            if show_leaderboard:
                cr3=draw_leaderboard()
                if pygame.mouse.get_pressed()[0] and cr3.collidepoint(pygame.mouse.get_pos()):
                    show_leaderboard=False

        # 音量按钮（所有界面统一显示，右上角）
        draw_volume_btn(8)
        # bet_mode 时强制确保在 game 界面（prep阶段保持，等用户确认）
        if bet_mode and screen_state not in ("game","solo","prep"):
            screen_state = "game"
        # 商店覆盖层：不要在这里每次打开都清缓存，否则同一局反复开关商店会重新刷新道具池
        _prev_screen_shop = screen_shop
        if screen_shop: draw_shop()
        # 目标选择弹窗（最顶层，只渲染）
        if target_select_mode:
            draw_target_select()
        # 外围下注弹窗
        if side_bet_mode and screen_state=="game":
            _br,_wr,_or,_cr,_ir3=draw_side_bet_popup()
            for _ev3 in pygame.event.get():
                if _ev3.type==pygame.QUIT: pygame.quit(); exit()
                elif _ev3.type==pygame.MOUSEBUTTONDOWN:
                    if _br.collidepoint(_ev3.pos): side_bet_type="bust"
                    elif _wr.collidepoint(_ev3.pos): side_bet_type="win"
                    elif _or.collidepoint(_ev3.pos) and side_bet_target and side_bet_type and side_bet_input:
                        amt3=parse_bet_input(side_bet_input)
                        if amt3>0:
                            client.send(f"[SIDE_BET]{side_bet_target}|{side_bet_type}|{amt3}\n".encode())
                        side_bet_mode=False
                    elif _cr.collidepoint(_ev3.pos): side_bet_mode=False
                elif _ev3.type==pygame.TEXTINPUT:
                    if len(side_bet_input)<10: side_bet_input+=_ev3.text
                elif _ev3.type==pygame.KEYDOWN:
                    if _ev3.key==pygame.K_BACKSPACE: side_bet_input=side_bet_input[:-1]
                    elif _ev3.key==pygame.K_ESCAPE: side_bet_mode=False
        draw_ach_popup()
        _draw_log_panel(HEIGHT)
        # 随机事件提示动画
        if event_name and event_announce_tick > 0:
            elapsed = anim_tick - event_announce_tick
            if elapsed < event_announce_dur:
                # 淡入淡出
                if elapsed < 30:
                    alpha = int(255 * elapsed / 30)
                elif elapsed > event_announce_dur - 40:
                    alpha = int(255 * (event_announce_dur - elapsed) / 40)
                else:
                    alpha = 255
                # 获取事件颜色
                from items import EVENTS as _EVS
                _ev = _EVS.get(current_event, {})
                _ecol = _ev.get("color", (200,200,200))
                # 背景
                _pw, _ph = 680, 160
                _px, _py = WIDTH//2 - _pw//2, HEIGHT//2 - _ph//2
                draw_rect_alpha(screen, (0,0,0), (_px,_py,_pw,_ph), int(alpha*0.8), 16)
                pygame.draw.rect(screen, _ecol,
                    pygame.Rect(_px,_py,_pw,_ph), 3, border_radius=16)
                # 标题
                _t1 = font_xl.render("⚡ 本局特殊规则 ⚡", True,
                    tuple(min(255, int(c * alpha/255)) for c in _ecol))
                screen.blit(_t1, (WIDTH//2 - _t1.get_width()//2, _py + 18))
                # 事件名
                _t2 = font_xl.render(event_name, True,
                    tuple(min(255, int(c * alpha/255)) for c in (255,255,255)))
                screen.blit(_t2, (WIDTH//2 - _t2.get_width()//2, _py + 62))
                # 描述
                _desc = _ev.get("desc","")
                _t3 = font_md.render(_desc, True,
                    tuple(min(255, int(c * alpha/255)) for c in (200,200,200)))
                screen.blit(_t3, (WIDTH//2 - _t3.get_width()//2, _py + 112))
            else:
                event_announce_tick = 0  # 动画结束
        # 翻牌动画覆盖层
        if card_reveal_queue:
            draw_card_reveal_animations()
        # 延迟发牌队列处理
        if card_reveal_pending:
            _pd = card_reveal_pending[0]
            _delay = _pd[5] - 1
            if _delay <= 0:
                queue_card_reveal(_pd[0],_pd[1],_pd[2],_pd[3],_pd[4])
                card_reveal_pending.pop(0)
                # 如果有完整手牌数据（发牌动画），在第2张开始动画时恢复手牌
                if len(_pd) > 6 and isinstance(_pd[6], list):
                    solo_hand[:] = _pd[6]
            else:
                card_reveal_pending[0] = _pd[:5] + (_delay,) + (_pd[6:] if len(_pd)>6 else ())
        draw_particles()
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()

if __name__=="__main__":
    try:
        main()
    except Exception as _main_ex:
        import traceback
        print(f"[主线程崩溃] {_main_ex}")
        traceback.print_exc()
        input("按回车退出...")
