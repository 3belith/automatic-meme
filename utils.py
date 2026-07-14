import re

# =========================================================
# 정규식
# =========================================================

# Discord 2000자 제한보다 조금 여유롭게 전송
DISCORD_MESSAGE_LIMIT = 1900

# 유니코드 이모지 제거
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "]",
    flags=re.UNICODE,
)


# =========================================================
# 문자열
# =========================================================

def normalize_text(text: str) -> str:
    """
    스팸 비교용 문자열 정규화
    """

    return re.sub(r"\s+", " ", text.strip().lower())


def remove_emojis(text: str) -> str:
    """
    AI가 실수로 출력한 이모지 제거
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


# =========================================================
# 히스토리
# =========================================================

def add_history(history, channel_id: int, speaker: str, text: str):
    """
    채널 히스토리 저장
    """

    history[channel_id].append(
        f"{speaker}: {text}"
    )


def build_prompt(history, channel_id, user_name, content):
    """
    Gemini 입력 생성
    """

    hist = history[channel_id]

    if not hist:
        return f"{user_name}: {content}"

    return (
        "[최근 대화 맥락]\n"
        + "\n".join(hist)
        + "\n\n"
        "[새 메시지]\n"
        + f"{user_name}: {content}"
    )


def build_batch(messages: list[str]):
    """
    여러 개의 짧은 메시지를 하나로 합침
    """

    if len(messages) == 1:
        return messages[0]

    joined = "\n".join(
        f"{i+1}. {msg}"
        for i, msg in enumerate(messages)
    )

    return (
        "사용자가 짧은 시간 안에 이어서 보낸 메시지다.\n"
        "하나의 대화처럼 자연스럽게 답변해라.\n\n"
        + joined
    )


# =========================================================
# Discord
# =========================================================

async def send_long_message(channel, text: str):
    """
    Discord 2000자 제한 대응
    """

    text = remove_emojis(text.strip())

    if not text:
        text = "왐마야 잠깐 말이 꼬였네."

    while text:

        await channel.send(
            text[:DISCORD_MESSAGE_LIMIT]
        )

        text = text[DISCORD_MESSAGE_LIMIT:]


async def try_delete_messages(messages):
    """
    여러 메시지 삭제
    """

    for msg in messages:

        try:
            await msg.delete()

        except Exception:
            pass


# =========================================================
# AI 응답
# =========================================================

def parse_ai_response(response: str):
    """
    AI 응답 파싱

    형식

    STATUS:ALLOW

    내용

    또는

    STATUS:DELETE

    내용
    """

    response = remove_emojis(response.strip())

    status = "ALLOW"

    if response.startswith("STATUS:DELETE"):
        status = "DELETE"
        response = response.replace(
            "STATUS:DELETE",
            "",
            1
        )

    elif response.startswith("STATUS:ALLOW"):
        response = response.replace(
            "STATUS:ALLOW",
            "",
            1
        )

    return status, response.strip()


# =========================================================
# Reply 판정
# =========================================================

def should_respond(client, message):
    """
    봇이 답해야 하는 메시지인지 판정
    """

    if message.author.bot:
        return False

    if message.guild is None:
        return True

    if client.user in message.mentions:
        return True

    ref = message.reference

    if (
        ref
        and ref.resolved
        and getattr(ref.resolved.author, "id", None)
        == client.user.id
    ):
        return True

    return False