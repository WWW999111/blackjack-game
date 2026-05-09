"""
商店、成就、称号、桌布系统 - 数据层
"""
import json, os, datetime, sys, importlib.util

def _imp(name, path):
    """加载模块，不污染 sys.modules（避免循环依赖导致半成品）"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    # 不加入 sys.modules，避免干扰外部加载顺序
    spec.loader.exec_module(mod)
    return mod

_here = os.path.dirname(os.path.abspath(__file__))
_items = _imp("items", os.path.join(_here, "items.py"))
ITEMS       = _items.ITEMS
ACHIEVEMENTS= _items.ACHIEVEMENTS
TABLECLOTHS = _items.TABLECLOTHS
CARD_BACKS  = _items.CARD_BACKS
TITLES      = _items.TITLES

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
SAVE_FILE = os.path.join(BASE_DIR, "save.json")

def _load():
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE,"r",encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {}

def _save(data):
    with open(SAVE_FILE,"w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_player_data(name):
    d = _load()
    pd = d.get("player_data",{}).get(name,{})
    return {
        "chips":        d.get("players",{}).get(name,0),
        "items":        pd.get("items",{}),         # {"透视眼镜":2, ...}
        "card_back":    pd.get("card_back",""),      # 当前选中卡背名
        "owned_backs":  pd.get("owned_backs",[]),    # 已购买卡背列表
        "tablecloth":   pd.get("tablecloth","default"),
        "owned_cloths": pd.get("owned_cloths",["default"]),
        "stats":        pd.get("stats",{}),          # 成就统计
        "achievements": pd.get("achievements",[]),   # 已解锁成就key列表
        "title":        pd.get("title",""),          # 当前称号
    }

def save_player_data(name, pd_update, chips=None):
    d = _load()
    if "player_data" not in d: d["player_data"] = {}
    if name not in d["player_data"]: d["player_data"][name] = {}
    d["player_data"][name].update(pd_update)
    if chips is not None:
        if "players" not in d: d["players"] = {}
        d["players"][name] = chips
    _save(d)

# ===== 动态定价 =====
# 定价区间设计：防止土豪随意购买，但也不让穷人完全买不起
# 筹码 < 2000：原价
# 筹码 2000-10000：原价 * (1 + (chips-2000)/8000 * 1.5)，最高2.5倍
# 筹码 > 10000：原价 * 2.5 + (chips-10000)*0.02（线性增长，无上限）
def get_dynamic_price(item_name, chips):
    """动态定价：穷人原价，富人高价，筹码越多越贵"""
    base = ITEMS.get(item_name, {}).get("price", 999)
    if chips <= 2000:
        return base
    elif chips <= 10000:
        mult = 1.0 + (chips - 2000) / 8000 * 1.5  # 1.0x -> 2.5x
        return int(base * mult)
    else:
        return int(base * 2.5 + (chips - 10000) * 0.02)

def get_item_cooldown(name, item_name):
    """检查道具冷却期"""
    d = _load()
    cooldowns = d.get("player_data",{}).get(name,{}).get("cooldowns", {})
    return cooldowns.get(item_name, 0)

def set_item_cooldown(name, item_name, games=2):
    """使用道具后设置N局冷却"""
    d = _load()
    if "player_data" not in d: d["player_data"] = {}
    if name not in d["player_data"]: d["player_data"][name] = {}
    cd = d["player_data"][name].get("cooldowns", {})
    cd[item_name] = games
    d["player_data"][name]["cooldowns"] = cd
    _save(d)

def tick_cooldowns(name):
    """每局开始时所有冷却-1"""
    d = _load()
    if "player_data" not in d or name not in d["player_data"]: return
    cd = d["player_data"][name].get("cooldowns", {})
    d["player_data"][name]["cooldowns"] = {k: v-1 for k,v in cd.items() if v > 1}
    _save(d)

# ===== 个人专属商店（肉鸽机制）=====
# 内存缓存个人商店（每次运行只在内存里，不写磁盘）
_pshop_cache = {}

def gen_personal_shop(name, game_id, chips):
    """每局给玩家生成3个专属推送道具（内存缓存，每局新ID就重新随机）"""
    import random
    key = f"{name}_{game_id}"
    if key in _pshop_cache:
        return _pshop_cache[key]
    # 按稀有度分池（排除盲盒自身）
    premium = [k for k,v in ITEMS.items() if v["price"] >= 800 and k != "命运盲盒"]
    mid     = [k for k,v in ITEMS.items() if 400 <= v["price"] < 800 and k != "命运盲盒"]
    low     = [k for k,v in ITEMS.items() if v["price"] < 400 and k != "命运盲盒"]
    # 权重抽取3个不重复道具（低价权重高）
    pool = [(k,1) for k in premium] + [(k,2) for k in mid] + [(k,3) for k in low]
    picks = []
    pool_copy = list(pool)
    for _ in range(min(3, len(pool_copy))):
        if not pool_copy: break
        total = sum(w for _,w in pool_copy)
        r = random.random() * total
        acc = 0
        for i,(item,w) in enumerate(pool_copy):
            acc += w
            if r <= acc:
                picks.append(item)
                pool_copy.pop(i)
                break
    # 盲盒始终有货（不受抽取影响）
    shop = {}
    if "命运盲盒" in ITEMS:
        shop["命运盲盒"] = {"price": 300, "qty": 99}
    for p in picks:
        shop[p] = {"price": get_dynamic_price(p, chips), "qty": 1}
    _pshop_cache[key] = shop
    # 清理旧缓存（只保留最近20个）
    if len(_pshop_cache) > 20:
        oldest = list(_pshop_cache.keys())[0]
        del _pshop_cache[oldest]
    return shop

def get_personal_shop(name, game_id, chips):
    """获取个人商店，不存在则生成"""
    return gen_personal_shop(name, game_id, chips)

def buy_item(name, item_name, game_id=None, chips_override=None):
    """购买道具：个人专属商店 + 动态定价 + 冷却检查"""
    pd = get_player_data(name)
    chips = chips_override or pd["chips"]
    is_custom = name.startswith("__custom__")

    if item_name == "命运盲盒":
        price = 300
        if chips < price: return False, "筹码不足"
        # 每局限购3个
        buy_cnt = get_blindbox_purchase_count(name, game_id or 0)
        if buy_cnt >= 3 and not is_custom:
            return False, "本局盲盒已购满3个"
        new_chips = chips - price
        save_player_data(name, {}, chips=new_chips)
        if not is_custom:
            inc_blindbox_purchase_count(name, game_id or 0)
        return True, f"opened:{_open_blind_box(name, game_id or 0)}"

    item = ITEMS.get(item_name)
    if not item: return False, "道具不存在"

    # 冷却检查（自定义模式跳过）
    if not is_custom:
        cd = get_item_cooldown(name, item_name)
        if cd > 0: return False, f"冷却{cd}局"

    # 价格（自定义原价，普通动态）
    price = item["price"] if is_custom else get_dynamic_price(item_name, chips)
    if chips < price: return False, f"筹码不足（需{price}）"

    # 个人商店库存检查（自定义跳过）
    if not is_custom and game_id is not None:
        shop = get_personal_shop(name, game_id, chips)
        if item_name not in shop or shop[item_name]["qty"] <= 0:
            return False, "本局推送中无此道具"
        # 消耗库存
        d = _load()
        key = f"pshop_{name}_{game_id}"
        if key in d and item_name in d[key]:
            d[key][item_name]["qty"] -= 1
            _save(d)

    items = pd["items"]
    items[item_name] = items.get(item_name, 0) + 1
    new_chips = chips - price
    save_player_data(name, {"items": items}, chips=new_chips)
    return True, f"购买成功！花费{price}"

# ===== 盲盒道具过期系统 =====
# 格式：box_items[name] = [{"item":iname, "expires_game":N}, ...]
# expires_game = 获得时的game_id + 3（第三局末失效）
_box_items_expire = {}  # 内存缓存

def add_box_item(name, item_name, current_game_id):
    """添加盲盒获得的道具，3局后过期，无冷却"""
    pd = get_player_data(name)
    items = pd["items"]
    items[item_name] = items.get(item_name, 0) + 1
    # 记录过期信息（存在 player_data 里）
    d = _load()
    if "player_data" not in d: d["player_data"] = {}
    if name not in d["player_data"]: d["player_data"][name] = {}
    box_items = d["player_data"][name].get("box_items", [])
    box_items.append({"item": item_name, "expires": current_game_id + 3})
    d["player_data"][name]["box_items"] = box_items
    save_player_data(name, {"items": items, "box_items": box_items})

def expire_box_items(name, current_game_id):
    """每局开始检查过期道具并移除"""
    d = _load()
    pd_raw = d.get("player_data", {}).get(name, {})
    box_items = pd_raw.get("box_items", [])
    if not box_items: return []
    expired = [bi["item"] for bi in box_items if bi["expires"] <= current_game_id]
    valid   = [bi for bi in box_items if bi["expires"] > current_game_id]
    if expired:
        # 从道具栏移除过期道具
        items = pd_raw.get("items", {})
        for iname in expired:
            if iname in items:
                items[iname] -= 1
                if items[iname] <= 0:
                    del items[iname]
        save_player_data(name, {"items": items, "box_items": valid})
    return expired  # 返回过期道具列表，用于日志提示

def is_box_item(name, item_name, current_game_id):
    """检查某道具是否是盲盒获得的（无冷却）"""
    d = _load()
    box_items = d.get("player_data",{}).get(name,{}).get("box_items",[])
    return any(bi["item"]==item_name and bi["expires"]>current_game_id for bi in box_items)

def get_lucky_buff(name):
    """获取超好运buff（BJ概率+88%持续N局）"""
    d = _load()
    return d.get("player_data",{}).get(name,{}).get("lucky_buff", None)
    # 返回 {"expires_game": N} 或 None

def set_lucky_buff(name, current_game_id, duration=3):
    """设置超好运buff"""
    d = _load()
    if "player_data" not in d: d["player_data"] = {}
    if name not in d["player_data"]: d["player_data"][name] = {}
    d["player_data"][name]["lucky_buff"] = {"expires": current_game_id + duration}
    _save(d)

def consume_lucky_buff(name, current_game_id):
    """检查buff是否有效，无效则清除，返回是否有buff"""
    d = _load()
    buff = d.get("player_data",{}).get(name,{}).get("lucky_buff", None)
    if buff is None: return False
    if buff["expires"] <= current_game_id:
        if "player_data" in d and name in d["player_data"]:
            d["player_data"][name]["lucky_buff"] = None
            _save(d)
        return False
    return True

def get_blindbox_purchase_count(name, game_id):
    """本局购买盲盒次数"""
    d = _load()
    key = f"box_buy_{name}_{game_id}"
    return d.get(key, 0)

def inc_blindbox_purchase_count(name, game_id):
    """增加本局盲盒购买次数"""
    d = _load()
    key = f"box_buy_{name}_{game_id}"
    d[key] = d.get(key, 0) + 1
    _save(d)

def _open_blind_box(name, current_game_id=0):
    """开箱逻辑，返回结果描述字符串"""
    import random
    r = random.random()
    if r < 0.02:        # 2% 特大奖：超好运（0.00-0.02）
        set_lucky_buff(name, current_game_id, duration=3)
        return "superjackpot:超好运"
    elif r < 0.12:      # 10% 大奖（0.02-0.12）
        prize = random.choice(["时光倒流","再来一次"])
        add_box_item(name, prize, current_game_id)
        return f"jackpot:{prize}"
    elif r < 0.50:      # 38% 保本（0.12-0.50）
        prize = random.choice(["透视眼镜","致盲烟雾","反弹镜像"])
        if prize in ITEMS:
            add_box_item(name, prize, current_game_id)
        return f"normal:{prize}"
    elif r < 0.70:      # 20% 安慰奖（0.50-0.70）
        return "nothing:谢谢参与"
    else:               # 30% 诅咒（0.70-1.00）
        curse = random.choice(["leak","blind","forced_hit"])
        return f"curse:{curse}"

def buy_card_back(name, back_name):
    pd = get_player_data(name)
    back = CARD_BACKS.get(back_name)
    if not back: return False, "皮肤不存在"
    if back_name in pd["owned_backs"]: return False, "已拥有此皮肤"
    if pd["chips"] < back["price"]: return False, f"筹码不足（需要{back['price']}）"
    owned = pd["owned_backs"] + [back_name]
    new_chips = pd["chips"] - back["price"]
    save_player_data(name, {"owned_backs":owned, "card_back":back_name}, chips=new_chips)
    return True, f"解锁【{back_name}】！剩余筹码: {new_chips}"

def buy_tablecloth(name, cloth_key):
    pd = get_player_data(name)
    cloth = TABLECLOTHS.get(cloth_key)
    if not cloth: return False, "桌布不存在"
    if cloth_key in pd["owned_cloths"]: return False, "已拥有此桌布"
    if pd["chips"] < cloth["price"]: return False, f"筹码不足（需要{cloth['price']}）"
    owned = pd["owned_cloths"] + [cloth_key]
    new_chips = pd["chips"] - cloth["price"]
    save_player_data(name, {"owned_cloths":owned, "tablecloth":cloth_key}, chips=new_chips)
    return True, f"解锁【{cloth['name']}】桌布！"

def equip_card_back(name, back_name):
    pd = get_player_data(name)
    if back_name not in pd["owned_backs"] and back_name != "":
        return False, "未拥有此皮肤"
    save_player_data(name, {"card_back": back_name})
    return True, f"已装备【{back_name}】"

def equip_tablecloth(name, cloth_key):
    pd = get_player_data(name)
    if cloth_key not in pd["owned_cloths"]:
        return False, "未拥有此桌布"
    save_player_data(name, {"tablecloth": cloth_key})
    return True, "桌布已更换"

def set_title(name, ach_key):
    pd = get_player_data(name)
    if ach_key not in pd["achievements"]: return False, "未解锁此成就"
    title = TITLES.get(ach_key,"")
    save_player_data(name, {"title": title})
    return True, f"称号已设为【{title}】"

def update_stats(name, **kwargs):
    """更新成就统计，并检查新成就"""
    pd = get_player_data(name)
    stats = pd["stats"]
    for k,v in kwargs.items():
        stats[k] = stats.get(k,0) + v
    unlocked = pd["achievements"]
    new_unlocked = []
    for key, ach in ACHIEVEMENTS.items():
        if key not in unlocked and ach["condition"](stats):
            unlocked.append(key)
            new_unlocked.append(key)
    save_player_data(name, {"stats":stats, "achievements":unlocked})
    return new_unlocked  # 返回本次新解锁的成就

def get_title_display(name):
    """返回带称号的显示名，如 [赌神] wf"""
    pd = get_player_data(name)
    t = pd.get("title","")
    return f"[{t}] {name}" if t else name

def use_item(name, item_name):
    """使用一次道具，返回 (success, msg)"""
    pd = get_player_data(name)
    items = pd["items"]
    cnt = items.get(item_name, 0)
    if cnt <= 0: return False, "没有此道具"
    items[item_name] = cnt - 1
    if items[item_name] == 0:
        del items[item_name]
    save_player_data(name, {"items": items})
    return True, f"使用了【{item_name}】"
