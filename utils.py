import re
from collections import deque

# =========================================================
# 공통 유틸
# =========================================================

# 유니코드 이모지 제거용
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "]",
    flags=re.UNICODE,
)


def normalize_text(text: str) -> str:
    """
    스팸 비교용 문자열 정규화
    """
    return re.sub(r"\s+", " ", text.strip().lower())


def remove_emojis(text: str) -> str:
    """
    AI가 실수로 출력한 이모지를 제거한다.
    """
    return EMOJI_RE.sub("", text)


def strip_mention(content: str, bot_id: int) -> str:
    """
    봇 멘션 제거
    """
    return (
        content.replace(f"<@{bot_id}>", "")
        .replace(f"<@!{bot_id}>", "")
        .strip()
    )


def add_history(history: dict, channel_id: int, speaker: str, text: str):
    """
    채널 히스토리 저장
    """
    history[channel_id].append(f"{speaker}: {text}")


def build_prompt(history: dict, channel_id: int, user_name: str, content: str):
    """
    Gemini에 전달할 프롬프트 생성
    """

    hist = history[channel_id]

    if not hist:
        return f"{user_name}: {content}"

    return (
        "[최근 대화 맥락]\n"
        + "\n".join(hist)
        + "\n\n"
        "[새 메시지]\n"
        f"{user_name}: {content}"
    )


def build_batch(messages: list[str]):
    """
    배치된 메시지를 하나의 입력으로 합침
    """

    if len(messages) == 1:
        return messages[0]

    return (
        "사용자가 짧은 시간 안에 이어서 보낸 메시지다.\n"
        "흐름을 이어서 하나의 대화처럼 답변해라.\n\n"
        + "\n".join(
            f"{i+1}. {msg}"
            for i, msg in enumerate(messages)
        )
    )


async def send_long_message(channel, text: str):
    """
    Discord 2000자 제한 대응
    """

    if not text:
        text = "왐마야 잠깐 말이 꼬였네."

    text = remove_emojis(text)

    for i in range(0, len(text), 1900):
        await channel.send(text[i:i + 1900])


async def try_delete_messages(messages):
    """
    여러 메시지 삭제
    """

    for msg in messages:
        try:
            await msg.delete()
        except Exception:
            pass


def remember_message(state, content):
    """
    최근 메시지 저장
    """

    state.recent_messages.append(normalize_text(content))


def clear_history(history: dict, limit: int):
    """
    혹시 deque를 안 쓰게 될 경우 대비
    """

    for key in history:
        while len(history[key]) > limit:
            history[key].popleft()