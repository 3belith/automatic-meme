import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

from config import (
    SPAM_WINDOW,
    SPAM_REPEAT_THRESHOLD,
    SPAM_STRIKE_LIMIT,
    SPAM_BLOCK_SECONDS,
    SPAM_WARN_COOLDOWN,
    logger,
)
from utils import (
    normalize_text,
    is_meaningless_spam,
    is_repeated_message,
    is_client_injection_attempt,
)

# =========================================================
# 상태 관리
# =========================================================
@dataclass
class SpamState:
    """사용자별 도배 상태"""
    recent_messages: deque = field(default_factory=lambda: deque(maxlen=SPAM_WINDOW))
    strikes: int = 0
    blocked_until: float = 0.0
    last_warn_at: float = 0.0


# 글로벌 상태
user_spam_states: dict[int, SpamState] = defaultdict(SpamState)
channel_histories: dict[int, deque] = defaultdict(lambda: deque(maxlen=10))


# =========================================================
# 도배 감지 및 처리
# =========================================================
def get_user_spam_state(user_id: int) -> SpamState:
    """사용자 도배 상태 획득"""
    return user_spam_states[user_id]


def remember_message(user_id: int, content: str) -> None:
    """사용자 메시지 기록"""
    state = get_user_spam_state(user_id)
    state.recent_messages.append(normalize_text(content))


def reduce_strikes(user_id: int) -> None:
    """도배 스트라이크 감소"""
    state = get_user_spam_state(user_id)
    state.strikes = max(0, state.strikes - 1)


def add_strike(user_id: int) -> None:
    """도배 스트라이크 추가"""
    state = get_user_spam_state(user_id)
    state.strikes += 1


def is_user_spam_blocked(user_id: int, now: float) -> bool:
    """사용자가 도배 블록 상태인지 확인"""
    state = get_user_spam_state(user_id)
    return now < state.blocked_until


def apply_spam_block(user_id: int, now: float) -> None:
    """도배 블록 적용"""
    state = get_user_spam_state(user_id)
    state.blocked_until = now + SPAM_BLOCK_SECONDS
    state.strikes = 0


def reset_spam_state(user_id: int) -> None:
    """사용자 도배 상태 초기화"""
    state = get_user_spam_state(user_id)
    state.recent_messages.clear()
    state.strikes = 0
    state.blocked_until = 0.0
    state.last_warn_at = 0.0


def should_warn_spam(user_id: int, now: float) -> bool:
    """도배 경고 표시 여부"""
    state = get_user_spam_state(user_id)
    return now - state.last_warn_at >= SPAM_WARN_COOLDOWN


def mark_spam_warned(user_id: int, now: float) -> None:
    """도배 경고 기록"""
    state = get_user_spam_state(user_id)
    state.last_warn_at = now


def is_spam_message(user_id: int, content: str) -> bool:
    """
    도배 메시지 판정 (클라이언트 사이드)
    
    판정 기준:
    1. 의미 없는 장문 (줄도배)
    2. 반복 메시지
    3. 규칙 변경 시도 (Injection)는 일반 메시지로 처리
    """
    norm = normalize_text(content)
    if not norm:
        return False
    
    # 의미 없는 도배 (줄도배)
    if is_meaningless_spam(content):
        return True
    
    # 반복 메시지
    state = get_user_spam_state(user_id)
    if is_repeated_message(list(state.recent_messages), norm, SPAM_REPEAT_THRESHOLD):
        return True
    
    return False


def get_spam_warning_message() -> str:
    """도배 경고 메시지"""
    warnings = (
        "왐마야 같은 말 계속 하면 내가 헷갈린다구, 한 번만 예쁘게 말해줘",
        "앵무새 모드 켰어? 자자 우리 돌멩이 채팅 정리하고 다시 말해보자",
        "복붙 버튼 누른 거 아니지? 한 번만 말해도 내가 알아듣는다니까",
        "채팅창 불난 줄 알았네 ㅋㅋ 알겠으니까 한 번만 말해줘",
    )
    import time
    return warnings[int(time.time()) % len(warnings)]


def should_timeout_spam_user(user_id: int) -> bool:
    """사용자 타임아웃 여부"""
    state = get_user_spam_state(user_id)
    return state.strikes >= SPAM_STRIKE_LIMIT


# =========================================================
# 대화 이력 관리
# =========================================================
def add_to_history(channel_id: int, speaker: str, text: str) -> None:
    """채널 대화 이력에 메시지 추가"""
    history = channel_histories[channel_id]
    history.append(f"{speaker}: {text}")


def get_channel_history(channel_id: int) -> list[str]:
    """채널 대화 이력 조회"""
    return list(channel_histories[channel_id])


def clear_channel_history(channel_id: int) -> None:
    """채널 대화 이력 초기화"""
    channel_histories[channel_id].clear()
