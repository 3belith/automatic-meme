import time
from dataclasses import dataclass, field
from collections import deque, defaultdict
from typing import Optional

import discord

from utils import normalize_text

# =========================================================
# 설정
# =========================================================

SPAM_REPEAT_THRESHOLD = 2
SPAM_WINDOW = 10
SPAM_STRIKE_LIMIT = 2

SPAM_BLOCK_SECONDS = 5
SPAM_TIMEOUT_SECONDS = 3

MEANINGLESS_LINE_THRESHOLD = 8

BATCH_WAIT_SECONDS = 2.5
MAX_BATCH_MESSAGES = 6

# =========================================================
# 상태 클래스
# =========================================================

@dataclass
class BatchState:
    channel_id: int
    channel: discord.abc.Messageable

    user_name: str

    source_messages: list[discord.Message] = field(default_factory=list)

    messages: list[str] = field(default_factory=list)

    updated_at: float = 0.0


@dataclass
class UserState:
    recent_messages: deque = field(
        default_factory=lambda: deque(maxlen=SPAM_WINDOW)
    )

    spam_strikes: int = 0

    spam_block_until: float = 0.0

    last_warn_at: float = 0.0

    batch: Optional[BatchState] = None

    batch_task = None


# =========================================================
# 전역 상태
# =========================================================

user_states = defaultdict(UserState)

# =========================================================
# 스팸 감지
# =========================================================

def remember_message(state: UserState, content: str):
    state.recent_messages.append(normalize_text(content))


def reduce_strike(state: UserState):
    state.spam_strikes = max(0, state.spam_strikes - 1)


def apply_block(state: UserState):
    state.spam_block_until = time.monotonic() + SPAM_BLOCK_SECONDS
    state.spam_strikes = 0


def is_meaningless_spam(content: str):

    lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip()
    ]

    if len(lines) < MEANINGLESS_LINE_THRESHOLD:
        return False

    counts = defaultdict(int)

    short = 0

    for line in lines:

        norm = normalize_text(line)

        counts[norm] += 1

        if len(norm) <= 2:
            short += 1

    if short >= MEANINGLESS_LINE_THRESHOLD:
        return True

    return any(v >= 5 for v in counts.values())


def is_repeat_spam(state: UserState, content: str):

    norm = normalize_text(content)

    if not norm:
        return False

    if is_meaningless_spam(content):
        return True

    same = sum(
        1
        for msg in state.recent_messages
        if msg == norm
    )

    return same >= SPAM_REPEAT_THRESHOLD - 1


def make_spam_reply():

    replies = [

        "왐마야 한 번만 말해도 알아듣는다구.",

        "앵무새 모드냐~ 같은 말은 한 번만 해줘.",

        "복붙 버튼 눌렀어? 채팅창 정리하자~",

        "채팅창이 난리났다 ㅋㅋ 한 번만 보내줘."

    ]

    return replies[int(time.time()) % len(replies)]


# =========================================================
# 배치
# =========================================================

def queue_batch(state: UserState, message: discord.Message, content: str):

    now = time.monotonic()

    if (
        state.batch is None
        or state.batch.channel_id != message.channel.id
    ):

        state.batch = BatchState(

            channel_id=message.channel.id,

            channel=message.channel,

            user_name=message.author.display_name,

            source_messages=[message],

            messages=[content],

            updated_at=now

        )

    else:

        batch = state.batch

        batch.updated_at = now

        batch.user_name = message.author.display_name

        batch.source_messages.append(message)

        if len(batch.messages) < MAX_BATCH_MESSAGES:

            batch.messages.append(content)

        else:

            batch.messages[-1] += "\n" + content


def clear_batch(state: UserState):

    if state.batch_task:

        state.batch_task.cancel()

    state.batch = None

    state.batch_task = None


# =========================================================
# 타임아웃
# =========================================================

async def timeout_member(message: discord.Message):

    if isinstance(message.channel, discord.DMChannel):
        return False

    guild = message.guild

    member = message.author

    if guild is None:
        return False

    if not isinstance(member, discord.Member):
        return False

    me = guild.me

    if me is None:
        return False

    if not me.guild_permissions.moderate_members:
        return False

    if member.top_role >= me.top_role:
        return False

    try:

        from datetime import timedelta

        await member.timeout(

            timedelta(seconds=SPAM_TIMEOUT_SECONDS),

            reason="도배"

        )

        return True

    except Exception:

        return False