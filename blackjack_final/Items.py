# ===== 道具定义 =====
ITEMS = {
    # ===== 主动道具 =====
    "透视眼镜": {
        "price": 500, "type": "active",
        "desc": "窥视庄家暗牌（仅自己可见）",
        "emoji": "👁", "color": (80,200,200),
    },
    "强买强卖": {
        "price": 600, "type": "active",
        "desc": "强制指定一名玩家下次必须要牌",
        "emoji": "🃏", "color": (200,140,0),
    },
    "再来一次": {
        "price": 800, "type": "active",
        "desc": "突破规则强制额外要一张牌（与时光倒流combo触发时空悖论）",
        "emoji": "🎲", "color": (100,180,255),
    },
    "致盲烟雾": {
        "price": 400, "type": "active",
        "desc": "使一名对手看不见自己的点数（显示???）",
        "emoji": "🌫", "color": (120,120,120),
    },
    "命运盲盒": {
        "price": 300, "type": "active",
        "desc": "2%特等奖/10%大奖/38%保本/20%谢谢参与/30%诅咒！纯粹的赌运气",
        "emoji": "📦", "color": (200,100,255),
    },
    # ===== 控牌类 =====
    "回炉重造": {
        "price": 600, "type": "active",
        "desc": "初始两张牌时可用：将手牌扔回重洗，重新抽两张",
        "emoji": "♻️", "color": (80,200,100),
    },
    "狸猫换太子": {
        "price": 800, "type": "active",
        "desc": "你的回合：将你一张手牌与庄家明牌互换",
        "emoji": "🎭", "color": (200,80,200),
    },
    "厄运信标": {
        "price": 700, "type": "active",
        "desc": "在牌堆顶埋雷：下一个要牌的人必抽10点牌",
        "emoji": "🧨", "color": (220,60,60),
    },
    # ===== 经济类 =====
    "第三只手": {
        "price": 500, "type": "active",
        "desc": "偷走指定玩家1个道具，若无道具则偷200筹码",
        "emoji": "🧤", "color": (150,100,50),
    },
    "吸血印记": {
        "price": 400, "type": "active",
        "desc": "下注阶段：绑定一名玩家，他赢了自动给你20%利润",
        "emoji": "🧛", "color": (150,0,100),
    },
    "杀贫济富": {
        "price": 300, "type": "passive",
        "desc": "拿到BJ且全场筹码第一时：强迫最穷玩家进贡100筹码",
        "emoji": "💸", "color": (220,180,0),
    },
    # ===== 全局类 =====
    "沉默干扰器": {
        "price": 600, "type": "active",
        "desc": "下注阶段：本局所有人无法使用主动道具（被动不受影响）",
        "emoji": "🤫", "color": (80,80,160),
    },
    "天平倾斜": {
        "price": 500, "type": "passive",
        "desc": "平局时不退钱，直接判你赢",
        "emoji": "⚖️", "color": (200,200,80),
    },
    # ===== 新主动道具 =====
    "回炉重造": {
        "price": 600, "type": "active",
        "desc": "初始发牌后，将两张手牌扔回重洗，重抽两张新牌",
        "emoji": "♻️", "color": (80,200,100),
        "phase": ["player_turn_initial"],  # 仅限初始两张牌
    },
    "狸猫换太子": {
        "price": 800, "type": "active",
        "desc": "将自己一张手牌与庄家明牌互换",
        "emoji": "🎭", "color": (200,100,0),
        "phase": ["player_turn"],
    },
    "厄运信标": {
        "price": 700, "type": "active",
        "desc": "在牌堆顶放置标记，下一个要牌的人（含庄家）必定抽到10点牌",
        "emoji": "🧨", "color": (220,40,40),
        "phase": ["player_turn","other_turn"],
    },
    "第三只手": {
        "price": 500, "type": "active",
        "desc": "偷取指定玩家1个道具；无道具则偷200筹码",
        "emoji": "🧤", "color": (100,60,200),
        "phase": ["player_turn","other_turn"],
    },
    "吸血印记": {
        "price": 400, "type": "active",
        "desc": "对一名玩家标记寄生，结算时若其赢了则扣除其20%利润给你",
        "emoji": "🧛", "color": (160,0,80),
        "phase": ["betting"],
    },
    "沉默干扰器": {
        "price": 600, "type": "active",
        "desc": "本局所有人无法使用主动道具（被动不受影响，你也不能用）",
        "emoji": "🤫", "color": (80,80,80),
        "phase": ["betting"],
    },
    # ===== 新被动道具 =====
    "杀贫济富": {
        "price": 300, "type": "passive",
        "trigger": "settle",
        "desc": "拿到BJ且全场筹码第一时，强迫筹码最少的玩家进贡100筹码",
        "emoji": "💸", "color": (255,200,0),
    },
    "天平倾斜": {
        "price": 500, "type": "passive",
        "trigger": "settle",
        "desc": "与庄家/对手平局时，判定为你赢（不退钱，直接拿赌注）",
        "emoji": "⚖️", "color": (180,180,0),
    },
    # ===== 被动道具 =====
    "时光倒流": {
        "price": 1000, "type": "passive",
        "trigger": "bust",
        "desc": "爆牌时自动触发，退回那张牌强制停牌",
        "emoji": "⏳", "color": (200,180,80),
    },
    "反弹镜像": {
        "price": 600, "type": "passive",
        "trigger": "targeted",
        "desc": "自动抵挡一次负面道具并反弹给使用者",
        "emoji": "🛡", "color": (100,200,100),
    },
    "点数修正": {
        "price": 800, "type": "passive",
        "trigger": "settle",
        "desc": "结算时若点数±1能赢或不爆则自动修改",
        "emoji": "📏", "color": (100,150,255),
    },
    "移花接木": {
        "price": 800, "type": "active",
        "desc": "初始两张牌时，与他人互换一张明牌",
        "emoji": "🔀", "color": (180,80,200),
    },
    "搏命契约": {
        "price": 300, "type": "active",
        "desc": "本局胜负筹码变为3.5倍（赢拿3.5倍，输扣3.5倍）",
        "emoji": "💣", "color": (220,50,50),
    },
    "金蝉脱壳": {
        "price": 1000, "type": "passive",
        "trigger": "settle",
        "desc": "输牌或爆牌时自动触发，本局不扣下注筹码",
        "emoji": "🪬", "color": (80,200,120),
    },
    "灵魂链接": {
        "price": 500, "type": "passive",
        "trigger": "start",
        "desc": "绑定全场筹码最多的玩家，他赢你分钱，他爆你跟着爆",
        "emoji": "🔗", "color": (255,100,150),
    },
}

ACTIVE_ITEMS  = {k:v for k,v in ITEMS.items() if v["type"]=="active"}
PASSIVE_ITEMS = {k:v for k,v in ITEMS.items() if v["type"]=="passive"}

# 每局限带规则
MAX_ACTIVE  = 1  # 最多1个主动道具
MAX_PASSIVE = 1  # 最多1个被动道具

# ===== 随机事件 =====
EVENTS = {
    "normal":   {"name": "普通局",       "desc": "",                                              "color": (200,200,200)},
    "speed":    {"name": "⚡ 极速局",     "desc": "上限17点！庄家13停牌，A+6=BJ，>17即爆！",     "color": (255,100,50)},
    "inflate":  {"name": "💰 通货膨胀",   "desc": "本局所有人下注额强制翻倍！",                   "color": (255,215,0)},
    "blind":    {"name": "🃏 盲牌模式",   "desc": "所有人第二张牌为暗牌！",                       "color": (150,80,200)},
    "bloodmoon":{"name": "🩸 血月之夜",   "desc": "无点数上限！谁大谁赢，但抽到黑桃直接爆牌！",   "color": (180,0,0)},
    "tornado":  {"name": "🌪️ 龙卷风",    "desc": "发完初始牌后，所有人手牌顺时针平移一位！",     "color": (100,200,255)},
    "jackpot":  {"name": "🏦 通货膨胀²", "desc": "赢家赔率×3！但爆牌者下一局禁止下注！",         "color": (255,180,0)},
    "silence":  {"name": "🤫 道具禁用",   "desc": "本局所有主动道具无法使用！",                   "color": (120,120,120)},
    "duel":     {"name": "⚔️ 决斗时代",   "desc": "本局所有平局触发西部决斗！",                   "color": (200,150,0)},
}

# ===== 成就 =====
ACHIEVEMENTS = {
    "winner":    {"name": "常胜将军", "desc": "累计赢20局",       "emoji": "🏆", "condition": lambda s: s.get("wins",0)>=20},
    "bust50":    {"name": "散财童子", "desc": "累计爆牌50次",     "emoji": "💸", "condition": lambda s: s.get("busts",0)>=50},
    "rich":      {"name": "财神爷",   "desc": "筹码累计超过50000","emoji": "💎", "condition": lambda s: s.get("peak_chips",0)>=50000},
    "blackjack": {"name": "BJ大师",   "desc": "累计BlackJack10次","emoji": "🃏", "condition": lambda s: s.get("blackjacks",0)>=10},
    "fivecard":  {"name": "五龙传说", "desc": "累计五龙5次",      "emoji": "🐉", "condition": lambda s: s.get("fivecards",0)>=5},
    "bankrupt":  {"name": "破产大王", "desc": "领取救济金10次",   "emoji": "🪙", "condition": lambda s: s.get("reliefs",0)>=10},
    "gambler":   {"name": "老赌鬼",   "desc": "累计参与100局",    "emoji": "🎰", "condition": lambda s: s.get("games",0)>=100},
    "surrender": {"name": "逃跑专家", "desc": "累计投降20次",     "emoji": "🏳", "condition": lambda s: s.get("surrenders",0)>=20},
    "paradox":   {"name": "时空裁判", "desc": "触发时空悖论5次",  "emoji": "⚡", "condition": lambda s: s.get("paradox",0)>=5},
    "side_bet":  {"name": "赌狗天才", "desc": "外围下注赢10次",   "emoji": "🎲", "condition": lambda s: s.get("side_wins",0)>=10},
    "duel_win":  {"name": "西部枪神", "desc": "决斗胜利5次",      "emoji": "⚔️", "condition": lambda s: s.get("duel_wins",0)>=5},
    "thief":     {"name": "神偷手",   "desc": "使用第三只手5次",  "emoji": "🧤", "condition": lambda s: s.get("steal",0)>=5},
}

# ===== 桌布 =====
TABLECLOTHS = {
    "default":  {"name": "默认绿毡",  "price": 0,     "color": (22,90,50)},
    "royal":    {"name": "皇家紫",    "price": 5000,  "color": (80,20,120)},
    "darkgold": {"name": "暗黑金",    "price": 10000, "color": (60,45,10)},
    "crimson":  {"name": "深红尊贵",  "price": 8000,  "color": (100,10,20)},
    "midnight": {"name": "午夜星空",  "price": 12000, "color": (10,15,50)},
}

# ===== 称号 =====
TITLES = {
    "winner":    "赌神",
    "bust50":    "散财童子",
    "rich":      "财神爷",
    "blackjack": "BJ大师",
    "fivecard":  "五龙传说",
    "bankrupt":  "破产大王",
    "gambler":   "老赌鬼",
    "surrender": "逃跑专家",
    "paradox":   "时空裁判",
    "side_bet":  "赌狗天才",
    "duel_win":  "西部枪神",
    "thief":     "神偷手",
}

# ===== 卡背皮肤 =====
CARD_BACKS = {
    "亡骸统御之牌":   {"price":1688,"effect":"death",        "color":(80,20,100),   "desc":"黑紫骷髅粒子环绕"},
    "凛冬冰眼之盾":   {"price":1688,"effect":"ice",          "color":(120,200,255), "desc":"冰晶雪花飘落"},
    "古殿契约之书":   {"price":1688,"effect":"ancient",      "color":(180,140,60),  "desc":"金色符文浮现"},
    "圣光祈愿之证":   {"price":1688,"effect":"holy",         "color":(255,240,150), "desc":"圣光金环扩散"},
    "圣辉天使之牌":   {"price":1688,"effect":"angel",        "color":(255,255,200), "desc":"白金羽毛飘落"},
    "圣辉战铠之盾":   {"price":1688,"effect":"armor",        "color":(200,180,100), "desc":"金甲光芒迸射"},
    "巨神兵核心之证": {"price":1688,"effect":"titan",        "color":(100,180,255), "desc":"蓝色能量波动"},
    "幽晶圣城之绘":   {"price":1688,"effect":"crystal",      "color":(150,100,255), "desc":"紫晶碎片漂浮"},
    "幽狱魔殿之扉":   {"price":1688,"effect":"hell",         "color":(150,0,50),    "desc":"暗红烈焰涌动"},
    "幽蓝圣羽之扉":   {"price":1688,"effect":"feather",      "color":(80,120,220),  "desc":"蓝羽缓缓飘落"},
    "星核战匣之证":   {"price":1688,"effect":"starcore",     "color":(200,220,255), "desc":"星核能量爆裂"},
    "星海幻梦之镜":   {"price":1688,"effect":"stardream",    "color":(100,150,255), "desc":"星海粒子漂移"},
    "星海秘典之扉":   {"price":1688,"effect":"starsecret",   "color":(60,80,200),   "desc":"蓝紫星光闪烁"},
    "星澜秘纹之扉":   {"price":1688,"effect":"starwave",     "color":(80,180,220),  "desc":"星澜波纹扩散"},
    "星界圣坛之扉":   {"price":1688,"effect":"starshrine",   "color":(180,200,255), "desc":"圣坛光柱直射"},
    "星界幽蓝战盾":   {"price":1688,"effect":"starblueshield","color":(40,80,180),  "desc":"幽蓝护盾脉冲"},
    "星盘秘典之扉":   {"price":1688,"effect":"stardisc",     "color":(120,160,240), "desc":"星盘旋转粒子"},
    "星穹圣镜之扉":   {"price":1688,"effect":"stardome",     "color":(160,200,255), "desc":"穹顶光芒倾泻"},
    "星舰先锋之盾":   {"price":1688,"effect":"starship",     "color":(0,200,255),   "desc":"星舰推进光轨"},
    "暗金血眼之牌":   {"price":1688,"effect":"bloodgold",    "color":(180,80,0),    "desc":"暗金血滴飞溅"},
    "月辉古堡之绘":   {"price":1688,"effect":"mooncastle",   "color":(200,200,255), "desc":"月光粒子弥漫"},
    "机械亡颅之证":   {"price":1688,"effect":"mech_skull",   "color":(80,200,180),  "desc":"绿色电路扫描"},
    "机甲核心之证":   {"price":1688,"effect":"mech_core",    "color":(0,220,200),   "desc":"机甲蓝光闪烁"},
    "沧澜冰镜之扉":   {"price":1688,"effect":"icemirror",    "color":(100,220,240), "desc":"冰蓝镜面折射"},
    "深蓝战匣之证":   {"price":1688,"effect":"deepblue",     "color":(20,40,180),   "desc":"深蓝能量涌动"},
    "炎狱魔盾之牌":   {"price":1688,"effect":"fireshield",   "color":(255,80,0),    "desc":"炎狱烈焰喷射"},
    "炎阳圣徽之牌":   {"price":1688,"effect":"sunseal",      "color":(255,180,0),   "desc":"烈日光晕爆发"},
    "炼狱魔心之盾":   {"price":1688,"effect":"hellcore",     "color":(200,40,0),    "desc":"魔心暗火燃烧"},
    "焚天炎核之牌":   {"price":1688,"effect":"inferno",      "color":(255,60,0),    "desc":"焚天火柱冲天"},
    "熔铁魔颅之盾":   {"price":1688,"effect":"molten",       "color":(220,100,20),  "desc":"熔铁液滴飞溅"},
    "猩红魔心之盾":   {"price":1688,"effect":"crimsonheart", "color":(200,0,40),    "desc":"猩红心跳脉冲"},
    "玄金龙首之证":   {"price":1688,"effect":"dragon",       "color":(180,150,0),   "desc":"金龙鳞片闪耀"},
    "白羽圣徽之牌":   {"price":1688,"effect":"whitewing",    "color":(240,240,255), "desc":"白羽圣光环绕"},
    "粉晶逆刃之牌":   {"price":1688,"effect":"pinkblade",    "color":(255,150,200), "desc":"粉晶碎刃飞旋"},
    "紫晶魔魂之牌":   {"price":1688,"effect":"purplesoul",   "color":(160,0,200),   "desc":"紫魂气息缭绕"},
    "繁花绮梦之绘":   {"price":1688,"effect":"flowers",      "color":(255,180,220), "desc":"粉色花瓣飘落"},
    "耀金圣徽之盾":   {"price":1688,"effect":"goldseal",     "color":(255,200,0),   "desc":"耀金圣光迸发"},
    "耀金圣甲之盾":   {"price":1688,"effect":"goldarmor",    "color":(220,180,0),   "desc":"金甲护盾旋转"},
    "苍蓝圣物之扉":   {"price":1688,"effect":"bluerelic",    "color":(80,160,220),  "desc":"苍蓝圣光脉动"},
    "苍蓝星核之扉":   {"price":1688,"effect":"bluestar",     "color":(60,140,255),  "desc":"星核蓝光爆裂"},
    "裂岩晶剑之牌":   {"price":1688,"effect":"rockblade",    "color":(150,120,80),  "desc":"岩晶碎裂飞散"},
    "赤焰心核之证":   {"price":1688,"effect":"redcore",      "color":(255,40,40),   "desc":"赤焰心核跳动"},
    "赤焰灵狼之绘":   {"price":1688,"effect":"redwolf",      "color":(220,60,20),   "desc":"赤焰狼影闪现"},
    "赤焰白龙之绘":   {"price":1688,"effect":"whitedragon",  "color":(255,120,80),  "desc":"白龙赤焰翻腾"},
    "赤焰龙盾之牌":   {"price":1688,"effect":"dragonshield", "color":(200,50,0),    "desc":"龙盾赤焰环绕"},
    "赤红战术核心":   {"price":1688,"effect":"redtactic",    "color":(220,20,20),   "desc":"战术核心红光扫射"},
    "鎏金凤羽之扉":   {"price":1688,"effect":"phoenix",      "color":(255,160,0),   "desc":"凤羽金光飞舞"},
    "鎏金誓约之牌":   {"price":1688,"effect":"goldvow",      "color":(200,160,20),  "desc":"鎏金誓约光环"},
    "霓虹猎影之证":   {"price":1688,"effect":"neon_hunt",    "color":(0,255,180),   "desc":"霓虹扫光追踪"},
    "霓虹逆棱之证":   {"price":1688,"effect":"neon_prism",   "color":(255,0,200),   "desc":"棱镜彩虹折射"},
    "霜鳞古龙之证":   {"price":1688,"effect":"frostdragon",  "color":(180,220,255), "desc":"霜鳞冰雾弥漫"},
    "黑金战匣之证":   {"price":1688,"effect":"blackgold",    "color":(180,140,20),  "desc":"黑金能量震荡"},
}
