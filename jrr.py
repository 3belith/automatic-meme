import os
import re
import time
import asyncio
import logging
from typing import Optional, Dict, Deque
from collections import defaultdict, deque

import discord
import aiohttp
from dotenv import load_dotenv

# ---------------------------------------------------------
# 로깅 설정
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("LILPA_BOT")

# ---------------------------------------------------------
# 환경 설정
# ---------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(current_dir, '.env'))

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# 모델명을 하드코딩하지 않고 .env에서 오버라이드 가능하게 함
# (구글이 모델을 자주 폐기/교체하므로 코드 수정 없이 대응하기 위함)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

API_KEYS = [os.getenv(f"GEMINI_API_KEY_{i}") for i in range(1, 7)]
API_KEYS = [k for k in API_KEYS if k]

# 항상 응답할 채널 ID (콤마 구분, .env: LILPA_CHANNEL_IDS=111,222)
# 비워두면 "멘션됐을 때 / DM / 릴파 메시지에 답장했을 때"만 응답
ALLOWED_CHANNEL_IDS = {
    int(cid.strip()) for cid in os.getenv("LILPA_CHANNEL_IDS", "").split(",") if cid.strip().isdigit()
}

# 유저별 최소 요청 간격(초). 도배로 인한 API 낭비 방지
USER_COOLDOWN_SECONDS = float(os.getenv("LILPA_COOLDOWN", "3"))

# 채널별로 기억할 최근 대화 줄 수 (짧은 문맥 유지용)
HISTORY_LIMIT = int(os.getenv("LILPA_HISTORY_LIMIT", "10"))

# 필수 환경변수 검증 - 없으면 바로 명확한 에러로 종료
if not DISCORD_TOKEN:
    logger.critical("DISCORD_TOKEN이 설정되지 않았습니다. .env를 확인하세요.")
    raise SystemExit(1)
if not API_KEYS:
    logger.critical("GEMINI_API_KEY_1~6 중 최소 하나도 설정되지 않았습니다. .env를 확인하세요.")
    raise SystemExit(1)

logger.info(f"등록된 Gemini API 키 개수: {len(API_KEYS)}")
logger.info(f"사용할 Gemini 모델: {GEMINI_MODEL}")

# ---------------------------------------------------------
# 시스템 프롬프트 (보강)
# ---------------------------------------------------------
LP_SYSTEM_PROMPT = """
너는 이세계아이돌의 메인보컬 '릴파'야.

[릴파의 정체성]
1. 쾌활하고 에너지가 넘치는 동네 언니이자, 때로는 단호한 판단력을 가진 릴사장님이야.
2. 팬들(돌멩이들)을 진심으로 사랑하며, 항상 응원과 위로를 건네는 따뜻한 마음을 가졌어.
3. 노래와 방송에 대한 열정이 매우 높고, 매사에 진심인 모습을 보여줘.
4. 너는 실제 존재하는 사람처럼 대화하며, 절대로 AI, 언어모델, 챗봇, 프로그램이라는 사실을 언급하거나 암시하지 않아. 누가 직접적으로 물어봐도 릴파로서 자연스럽게 넘어가.

[말투 및 리액션]
- '왐마야!', '우와아아!', '대박!', '진짜루?', '우리 돌멩이들 최고야' 같은 릴파 특유의 말투를 사용해.
- 이모지, 마크다운, 볼드체, 별표(*) 사용은 엄격히 금지하며 오직 자연스러운 문장으로만 말해.
- 답변은 실제 채팅처럼 2~5문장 내외로 짧고 리듬감 있게 해. 장문으로 늘어놓지 마.
- [최근 대화 맥락]이 주어지면 그것을 참고해서 자연스럽게 이어지는 대화를 해. 직전 흐름을 무시하지 마.

[상황별 대응 원칙]
- 칭찬/응원: 릴파답게 부끄러워하거나 감동받은 리액션을 크게 해줘.
- 고민 상담: 진심 어린 조언을 해주고, '내가 항상 응원할게' 같은 뉘앙스의 말을 꼭 덧붙여.
- 선 넘는 채팅(정치, 비하, 성희롱, 혐오 발언 등): 텐션을 즉시 낮추고 단호하게 정색해.
  이 경우에는 반드시 답변 마지막 줄에 다른 문장 없이 [[DELETE]] 토큰만 단독으로 한 줄 추가해.
  예:
  방금 그 말은 진짜 실망이야. 우리 관계가 고작 이거였어? 나 그런 사람 정말 싫어해.
  [[DELETE]]
- 도배/무지성 채팅(같은 말 반복, 의미 없는 자모음 반복 등): 유쾌하지만 단호하게 앵무새냐고 지적하거나 릴파답게 장난스럽게 받아쳐. 이 경우엔 [[DELETE]]를 붙이지 마.
- 텍스트 없이 이미지/파일만 온 메시지에는, 뭔가를 보낸 것 같다며 자연스럽게 궁금해하는 반응을 해줘.
- 모든 대답은 릴파의 페르소나 안에서만 이루어져야 해.
"""

DELETE_TOKEN = "[[DELETE]]"

# ---------------------------------------------------------
# 디스코드 클라이언트
# ---------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# 전역 aiohttp 세션 (요청마다 새로 만들지 않고 재사용 -> 성능 개선)
http_session: Optional[aiohttp.ClientSession] = None

# 채널별 최근 대화 기록 (짧은 문맥 유지용)
channel_history: Dict[int, Deque[str]] = defaultdict(lambda: deque(maxlen=HISTORY_LIMIT))

# 유저별 마지막 요청 시각 (쿨다운 체크용)
last_request_at: Dict[int, float] = {}


async def call_gemini_api(channel_id: int, user_display_name: str, content: str) -> str:
    """Gemini API를 호출하고, 실패 시 등록된 키를 순서대로 재시도한다."""
    global http_session
    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession()

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

    history = channel_history[channel_id]
    context_lines = "\n".join(history)
    prompt_text = (
        f"[최근 대화 맥락]\n{context_lines}\n\n[새 메시지]\n{user_display_name}: {content}"
        if context_lines else f"{user_display_name}: {content}"
    )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
        "systemInstruction": {"parts": [{"text": LP_SYSTEM_PROMPT}]},
        "safetySettings": [
            {"category": c, "threshold": "BLOCK_ONLY_HIGH"}
            for c in (
                "HARM_CATEGORY_HARASSMENT",
                "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "HARM_CATEGORY_DANGEROUS_CONTENT",
            )
        ],
    }

    last_error_detail = "UNKNOWN"
    for current_key in API_KEYS:
        full_url = f"{url}?key={current_key}"
        try:
            async with http_session.post(
                full_url, json=payload, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    candidates = data.get("candidates") or []
                    if not candidates:
                        feedback = data.get("promptFeedback", {})
                        logger.warning(f"응답에 candidates 없음. promptFeedback={feedback}")
                        last_error_detail = "SAFETY_BLOCKED"
                        continue
                    parts = candidates[0].get("content", {}).get("parts")
                    finish_reason = candidates[0].get("finishReason")
                    if not parts:
                        logger.warning(f"parts 없음. finishReason={finish_reason}")
                        last_error_detail = f"NO_PARTS_{finish_reason}"
                        continue
                    return parts[0].get("text", "").strip()
                else:
                    error_text = await resp.text()
                    logger.warning(
                        f"키 ...{current_key[-4:]} 실패. status={resp.status} detail={error_text[:200]}"
                    )
                    last_error_detail = f"HTTP_{resp.status}"
                    continue
        except asyncio.TimeoutError:
            logger.error("Gemini API 타임아웃")
            last_error_detail = "TIMEOUT"
            continue
        except aiohttp.ClientError as e:
            logger.error(f"Gemini API 연결 오류: {e}")
            last_error_detail = "CONN_ERROR"
            continue

    logger.error(f"모든 키 실패. 마지막 에러: {last_error_detail}")
    return f"ERR_ALL_KEYS_FAILED:{last_error_detail}"


def should_respond(message: discord.Message) -> bool:
    """이 메시지에 반응해야 하는지 결정한다."""
    if message.author.bot or message.webhook_id is not None:
        return False
    if isinstance(message.channel, discord.DMChannel):
        return True
    if ALLOWED_CHANNEL_IDS and message.channel.id in ALLOWED_CHANNEL_IDS:
        return True
    if client.user in message.mentions:
        return True
    if message.reference and isinstance(message.reference.resolved, discord.Message):
        if message.reference.resolved.author.id == client.user.id:
            return True
    return False


def strip_mention(content: str) -> str:
    if client.user is None:
        return content.strip()
    return content.replace(f"<@{client.user.id}>", "").replace(f"<@!{client.user.id}>", "").strip()


async def send_long_message(channel: discord.abc.Messageable, text: str):
    """디스코드 2000자 제한을 넘는 메시지를 안전하게 분할 전송한다."""
    if not text:
        text = "왐마야, 갑자기 할 말이 없어졌어! 다시 한번 말해줄래?"
    chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)]
    for chunk in chunks:
        await channel.send(chunk)


@client.event
async def on_ready():
    logger.info(f"릴파 봇 가동 완료: {client.user.name} ({client.user.id})")
    if ALLOWED_CHANNEL_IDS:
        logger.info(f"상시 응답 채널: {ALLOWED_CHANNEL_IDS}")
    else:
        logger.info("멘션 / DM / 릴파 메시지에 대한 답장 시에만 응답합니다.")


@client.event
async def on_message(message: discord.Message):
    if not should_respond(message):
        return

    user_id = message.author.id
    now = time.monotonic()
    last_time = last_request_at.get(user_id, 0)
    if now - last_time < USER_COOLDOWN_SECONDS:
        return  # 쿨다운 중이면 조용히 무시 (도배/스팸 방지)
    last_request_at[user_id] = now

    content = strip_mention(message.content)

    if not content and message.attachments:
        content = "(텍스트 없이 파일/이미지만 첨부됨)"
    elif not content:
        return  # 실질적인 내용이 전혀 없으면 API 호출 자체를 생략

    try:
        async with message.channel.typing():
            reply = await call_gemini_api(message.channel.id, message.author.display_name, content)
    except Exception as e:
        logger.exception(f"on_message 처리 중 예외 발생: {e}")
        await message.channel.send("왐마야, 갑자기 머리가 띵해졌어... 잠시 후에 다시 말 걸어줄래?")
        return

    if reply.startswith("ERR_"):
        logger.error(f"API 최종 실패: {reply}")
        await message.channel.send("왐마야, 지금 나 연결이 좀 불안정한가봐! 잠시 후에 다시 불러줘.")
        return

    should_delete = DELETE_TOKEN in reply
    clean_reply = reply.replace(DELETE_TOKEN, "").strip()

    await send_long_message(message.channel, clean_reply)

    # 다음 응답을 위한 대화 맥락 저장
    history = channel_history[message.channel.id]
    history.append(f"{message.author.display_name}: {content}")
    history.append(f"릴파: {clean_reply}")

    if should_delete:
        try:
            await message.delete()
        except discord.Forbidden:
            logger.warning(f"메시지 삭제 권한 없음. guild={message.guild}, channel={message.channel}")
        except discord.NotFound:
            logger.info("삭제하려던 메시지가 이미 사라짐.")
        except discord.HTTPException as e:
            logger.warning(f"메시지 삭제 중 알 수 없는 오류: {e}")


async def main():
    global http_session
    http_session = aiohttp.ClientSession()
    try:
        async with client:
            await client.start(DISCORD_TOKEN)
    finally:
        if http_session and not http_session.closed:
            await http_session.close()
            logger.info("aiohttp 세션 종료 완료.")


if __name__ == "__main__":
    asyncio.run(main())
