"""
卡背特效系统 - 每种皮肤对应独特粒子/光效
"""
import pygame
import math
import random

def get_effect_particles(effect, cx, cy, tick):
    """
    根据特效类型返回粒子列表
    每帧调用，返回 [(x,y,r,color,alpha), ...]
    cx,cy = 牌的中心坐标
    """
    pts = []
    t = tick * 0.05

    # ===== 通用工具 =====
    def orbit(n, radius, speed, size, color, wobble=0):
        for i in range(n):
            angle = t * speed + math.pi*2/n*i
            r2 = radius + math.sin(t*3+i)*wobble
            x = cx + math.cos(angle)*r2
            y = cy + math.sin(angle)*r2
            pts.append((x, y, size, color, 200))

    def pulse_ring(radius, color, width=2):
        for i in range(36):
            angle = math.pi*2/36*i
            r2 = radius + math.sin(t*2)*6
            x = cx + math.cos(angle)*r2
            y = cy + math.sin(angle)*r2
            pts.append((x, y, width, color, 160))

    def rain(n, color, speed=1.5):
        for i in range(n):
            phase = (t*speed + i*0.37) % 1.0
            x = cx + (i - n//2) * 8 + math.sin(t+i)*3
            y = cy - 60 + phase * 130
            alpha = int(200*(1-phase))
            pts.append((x, y, 2, color, alpha))

    def sparks(n, color, radius=40):
        for i in range(n):
            angle = t*2 + math.pi*2/n*i
            phase = (t*1.5 + i*0.5) % 1.0
            r = radius * phase
            x = cx + math.cos(angle)*r
            y = cy + math.sin(angle)*r
            alpha = int(220*(1-phase))
            pts.append((x, y, 3, color, alpha))

    def spiral(n, color, turns=2):
        for i in range(n):
            phase = i/n
            angle = phase*math.pi*2*turns + t*2
            r = phase*50
            x = cx + math.cos(angle)*r
            y = cy + math.sin(angle)*r
            pts.append((x, y, 2, color, int(200*phase)))

    def heartbeat(color):
        scale = 1 + 0.15*abs(math.sin(t*4))
        for i in range(24):
            angle = math.pi*2/24*i
            r = 35*scale
            x = cx + math.cos(angle)*r
            y = cy + math.sin(angle)*r
            pts.append((x, y, 3, color, 180))

    # ===== 各特效实现 =====
    e = effect

    if e == "death":      # 亡骸 - 黑紫骷髅粒子
        orbit(8, 38, 1.2, 3, (150,0,180), wobble=5)
        sparks(12, (80,0,100), 45)
        pulse_ring(30, (100,0,150))

    elif e == "ice":      # 凛冬 - 冰晶雪花
        rain(10, (180,220,255), 0.8)
        orbit(6, 32, -0.8, 4, (200,240,255), wobble=3)
        pulse_ring(24, (150,200,255))

    elif e == "ancient":  # 古殿 - 金色符文
        orbit(6, 35, 0.6, 3, (200,160,40))
        spiral(30, (220,180,60))
        pulse_ring(20, (180,140,30))

    elif e == "holy":     # 圣光 - 金环扩散
        for i in range(3):
            phase = (t*0.5 + i*0.33) % 1.0
            r = 20 + phase*40
            alpha = int(200*(1-phase))
            pulse_ring(int(r*1.5), (255,240,150), 2)
        orbit(8, 36, 1.0, 3, (255,220,100))

    elif e == "angel":    # 圣辉天使 - 白金羽毛
        rain(8, (255,255,220), 0.6)
        orbit(10, 34, 0.7, 2, (240,240,200), wobble=8)
        pulse_ring(28, (255,250,180))

    elif e == "armor":    # 圣辉战铠 - 金甲光芒
        sparks(16, (220,180,60), 42)
        orbit(4, 30, 2.0, 5, (200,160,40))
        pulse_ring(16, (180,140,20), 3)

    elif e == "titan":    # 巨神兵 - 蓝色能量波
        for i in range(3):
            phase = (t*0.7 + i*0.33) % 1.0
            r = 15 + phase*45
            alpha = int(180*(1-phase))
            for j in range(20):
                angle = math.pi*2/20*j
                x = cx + math.cos(angle)*r
                y = cy + math.sin(angle)*r
                pts.append((x,y,2,(100,180,255),alpha))
        orbit(6, 28, 1.5, 3, (80,160,240))

    elif e == "crystal":  # 幽晶 - 紫晶碎片
        for i in range(12):
            angle = t*0.8 + math.pi*2/12*i
            r = 30 + math.sin(t*2+i*0.5)*10
            x = cx + math.cos(angle)*r
            y = cy + math.sin(angle)*r
            size = 2 + int(math.sin(t*3+i)*1.5)
            pts.append((x,y,size,(160,100,255),180))
        pulse_ring(18, (130,80,220))

    elif e == "hell":     # 幽狱 - 暗红烈焰
        for i in range(14):
            phase = (t*2 + i*0.23) % 1.0
            x = cx + (i-7)*7 + math.sin(t*3+i)*4
            y = cy + 50 - phase*100
            alpha = int(200*(1-phase))
            pts.append((x,y,3,(150,0,50),alpha))
        pulse_ring(16, (120,0,40), 3)

    elif e == "feather":  # 幽蓝圣羽 - 蓝羽飘落
        rain(8, (100,150,240), 0.7)
        orbit(8, 32, 0.6, 3, (80,120,220), wobble=10)

    elif e == "starcore": # 星核 - 星核爆裂
        sparks(20, (200,220,255), 50)
        orbit(5, 25, 3.0, 4, (180,200,255))
        pulse_ring(20, (160,180,255), 2)

    elif e in ("stardream","starsecret","starwave","starshrine",
               "starblueshield","stardisc","stardome","starship"):
        # 星系列 - 各自微调颜色和轨道数
        colors = {
            "stardream":    (100,150,255), "starsecret":  (80,100,220),
            "starwave":     (80,180,220),  "starshrine":  (180,200,255),
            "starblueshield":(40,80,180),  "stardisc":    (120,160,240),
            "stardome":     (160,200,255), "starship":    (0,200,255),
        }
        c = colors.get(e,(140,180,255))
        n = {"stardream":8,"starsecret":6,"starwave":10,"starshrine":7,
             "starblueshield":5,"stardisc":9,"stardome":8,"starship":6}.get(e,7)
        orbit(n, 34, 1.0+n*0.05, 3, c, wobble=5)
        spiral(20, c)
        pulse_ring(18, c)

    elif e == "bloodgold": # 暗金血眼 - 暗金血滴
        for i in range(10):
            phase = (t*1.8+i*0.3)%1.0
            x = cx + (i-5)*9
            y = cy - 40 + phase*80
            alpha = int(220*(1-phase))
            pts.append((x,y,3,(180,60,0),alpha))
        orbit(6, 30, 1.5, 3, (160,80,0))

    elif e == "mooncastle": # 月辉古堡 - 月光粒子
        for i in range(20):
            angle = t*0.3 + math.pi*2/20*i
            r = 35 + math.sin(t+i*0.5)*8
            x = cx + math.cos(angle)*r
            y = cy + math.sin(angle)*r
            alpha = int(140+60*math.sin(t*2+i))
            pts.append((x,y,2,(200,200,255),alpha))

    elif e in ("mech_skull","mech_core"): # 机械系 - 电路扫描
        c = (0,220,180) if e=="mech_skull" else (0,200,220)
        for i in range(8):
            x1 = cx - 40 + i*10
            phase = (t*1.5+i*0.2)%1.0
            y = cy - 50 + phase*100
            pts.append((x1,y,2,c,int(200*(1-phase))))
        orbit(4, 28, 2.5, 3, c)
        pulse_ring(14, c)

    elif e == "icemirror": # 沧澜冰镜 - 冰蓝折射
        for i in range(16):
            angle = math.pi*2/16*i + t*0.5
            r = 32 + math.sin(t*2+i)*6
            x = cx + math.cos(angle)*r
            y = cy + math.sin(angle)*r
            pts.append((x,y,2,(120,220,240),160))
        rain(6, (180,230,255), 0.9)

    elif e == "deepblue":  # 深蓝战匣
        orbit(7, 33, 0.8, 3, (20,60,200), wobble=6)
        pulse_ring(16, (40,80,200), 2)

    elif e in ("fireshield","sunseal","hellcore","inferno","molten"):
        fire_colors = {
            "fireshield":(255,80,0), "sunseal":(255,180,0),
            "hellcore":(200,40,0),   "inferno":(255,60,0), "molten":(220,100,20)
        }
        c = fire_colors.get(e,(255,80,0))
        for i in range(14):
            phase = (t*2.5+i*0.22)%1.0
            x = cx+(i-7)*7+math.sin(t*4+i)*5
            y = cy+45-phase*95
            alpha=int(220*(1-phase))
            pts.append((x,y,3,c,alpha))
        orbit(5, 28, 2.0, 4, c)

    elif e == "crimsonheart": # 猩红 - 心跳
        heartbeat((200,0,40))
        sparks(10, (180,0,30), 38)

    elif e == "dragon":    # 玄金龙 - 金龙鳞片
        for i in range(14):
            angle = t*1.2+math.pi*2/14*i
            r = 30+math.sin(t*2+i)*8
            x=cx+math.cos(angle)*r; y=cy+math.sin(angle)*r
            size=3+int(math.sin(t*3+i)*1)
            pts.append((x,y,size,(200,160,0),190))
        pulse_ring(14,(180,140,0),3)

    elif e == "whitewing":  # 白羽圣徽
        rain(8,(240,240,255),0.65)
        orbit(8,34,0.7,3,(220,220,255),wobble=8)
        pulse_ring(22,(200,200,255))

    elif e == "pinkblade":  # 粉晶逆刃
        sparks(14,(255,150,200),40)
        orbit(7,30,1.8,3,(240,120,180))
        pulse_ring(16,(255,180,210))

    elif e == "purplesoul": # 紫晶魔魂
        orbit(9,35,1.3,3,(160,0,200),wobble=7)
        spiral(25,(140,0,180))
        pulse_ring(18,(120,0,160),2)

    elif e == "flowers":    # 繁花绮梦 - 花瓣飘落
        for i in range(12):
            phase=(t*0.8+i*0.25)%1.0
            x=cx+(i-6)*9+math.sin(t+i*0.8)*12
            y=cy-55+phase*120
            alpha=int(200*(1-phase))
            pts.append((x,y,4,(255,180,220),alpha))
        orbit(6,30,0.5,3,(255,160,200),wobble=12)

    elif e in ("goldseal","goldarmor"): # 耀金系
        c=(255,200,0) if e=="goldseal" else (220,180,0)
        orbit(10,36,1.1,3,c)
        sparks(14,c,42)
        pulse_ring(20,c,2)

    elif e in ("bluerelic","bluestar"): # 苍蓝系
        c=(80,160,220) if e=="bluerelic" else (60,140,255)
        orbit(7,32,1.0,3,c,wobble=5)
        pulse_ring(18,c)
        sparks(10,c,38)

    elif e == "rockblade":  # 裂岩晶剑
        for i in range(10):
            angle=t*0.6+math.pi*2/10*i
            r=28+math.sin(t*2+i)*10
            x=cx+math.cos(angle)*r; y=cy+math.sin(angle)*r
            pts.append((x,y,3,(150,120,80),170))
        sparks(8,(130,100,60),35)

    elif e in ("redcore","redwolf","whitedragon","dragonshield","redtactic"):
        fire_r = {
            "redcore":(255,40,40),"redwolf":(220,60,20),
            "whitedragon":(255,120,80),"dragonshield":(200,50,0),
            "redtactic":(220,20,20)
        }
        c=fire_r.get(e,(220,40,0))
        for i in range(12):
            phase=(t*2.2+i*0.25)%1.0
            x=cx+(i-6)*8+math.sin(t*3+i)*4
            y=cy+40-phase*85
            alpha=int(210*(1-phase))
            pts.append((x,y,3,c,alpha))
        orbit(6,28,1.8,4,c)

    elif e == "phoenix":    # 鎏金凤羽 - 凤羽飞舞
        for i in range(10):
            phase=(t*1.2+i*0.3)%1.0
            angle=t*2+math.pi*2/10*i
            r=phase*45
            x=cx+math.cos(angle)*r; y=cy+math.sin(angle)*r
            alpha=int(220*(1-phase))
            pts.append((x,y,3,(255,160,0),alpha))
        orbit(6,32,1.5,3,(220,140,0),wobble=8)

    elif e == "goldvow":    # 鎏金誓约
        pulse_ring(24,(200,160,20))
        orbit(8,34,0.9,3,(180,140,0))
        sparks(10,(220,160,20),38)

    elif e == "neon_hunt":  # 霓虹猎影
        neon_colors=[(0,255,180),(0,200,255),(100,255,200)]
        for ci,nc in enumerate(neon_colors):
            orbit(5,28+ci*5,1.0+ci*0.3,2,nc)
        for i in range(20):
            phase=(t*2+i*0.15)%1.0
            x=cx-80+phase*160; y=cy+math.sin(phase*math.pi*4)*20
            pts.append((x,y,2,(0,255,180),int(180*(1-phase))))

    elif e == "neon_prism": # 霓虹逆棱 - 棱镜彩虹
        rainbow=[(255,0,100),(255,100,0),(255,255,0),(0,255,100),(0,100,255),(180,0,255)]
        for ci,c in enumerate(rainbow):
            orbit(4,20+ci*4,1.0+ci*0.2,2,c)

    elif e == "frostdragon":# 霜鳞古龙
        rain(8,(180,220,255),0.7)
        orbit(8,34,-0.9,3,(160,200,240),wobble=6)
        pulse_ring(20,(140,180,220))

    elif e == "blackgold":  # 黑金战匣
        orbit(8,35,1.2,3,(180,140,20),wobble=5)
        sparks(12,(160,120,0),40)
        pulse_ring(18,(140,100,10),2)

    else:  # 默认 - 金色星光
        orbit(6,32,1.0,3,(212,175,55))
        pulse_ring(16,(180,140,40))

    return pts


def draw_card_effect(screen, effect, cx, cy, tick):
    """在屏幕上绘制卡背特效"""
    pts = get_effect_particles(effect, cx, cy, tick)
    for (x,y,r,color,alpha) in pts:
        if r < 1: continue
        try:
            s = pygame.Surface((r*2+2, r*2+2), pygame.SRCALPHA)
            pygame.draw.circle(s, (*color[:3], alpha), (r+1,r+1), r)
            screen.blit(s, (int(x)-r, int(y)-r))
        except:
            pass
