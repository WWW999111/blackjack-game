import random

suits  = ['♥', '♦', '♠', '♣']
ranks  = ['2','3','4','5','6','7','8','9','10','J','Q','K','A']
values = {
    '2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,
    '10':10,'J':10,'Q':10,'K':10,'A':11
}

FIVE_CARD_CHARLIE = True   # 五龙规则开关
BANKER_FORCE_HIT  = 16     # 真人庄家强制要牌线（<=此值必须要牌）

def get_deck():
    return [s+r for s in suits for r in ranks]

def get_rank(card):
    return card[1:]

def get_value(card):
    return values[get_rank(card)]

def is_ten(card):
    return get_rank(card) in ['10','J','Q','K']

def is_ace(card):
    return get_rank(card) == 'A'

def calc(hand):
    """计算手牌点数，A 自动按最优计算"""
    total = sum(values[get_rank(c)] for c in hand)
    aces  = sum(1 for c in hand if is_ace(c))
    while total > 21 and aces:
        total -= 10
        aces  -= 1
    return total

def is_soft(hand):
    """是否是软手（含有算作 11 的 A）"""
    total = sum(values[get_rank(c)] for c in hand)
    aces  = sum(1 for c in hand if is_ace(c))
    while total > 21 and aces:
        total -= 10
        aces  -= 1
    return aces > 0 and total <= 21

def is_blackjack(hand):
    """是否是 BlackJack（仅限初始两张：A + T）"""
    if len(hand) != 2:
        return False
    return (is_ace(hand[0]) and is_ten(hand[1])) or \
           (is_ace(hand[1]) and is_ten(hand[0]))

def is_five_card_charlie(hand):
    """五龙：5 张牌未爆牌，直接胜"""
    return FIVE_CARD_CHARLIE and len(hand) >= 5 and calc(hand) <= 21

def can_split(hand):
    """是否可以分牌（两张点数相同）"""
    if len(hand) != 2:
        return False
    return values[get_rank(hand[0])] == values[get_rank(hand[1])]

def is_split_aces(hand):
    """是否是分 A 后的手牌（两张都是 A）"""
    return len(hand) == 2 and all(is_ace(c) for c in hand)

def dealer_should_hit(hand):
    """系统庄家软 17 规则"""
    val = calc(hand)
    if val < 17:
        return True
    if val == 17 and is_soft(hand):
        return True
    return False

def banker_must_hit(hand):
    """真人庄家强制要牌线：<= BANKER_FORCE_HIT 必须要牌"""
    return calc(hand) <= BANKER_FORCE_HIT
