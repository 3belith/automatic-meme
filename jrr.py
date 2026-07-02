import os
import asyncio
import time
import discord
import openai
from dotenv import load_dotenv
from collections import defaultdict

# 환경 변수 로드
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, '.env')
load_dotenv(env_path)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# AsyncOpenAI 비동기 클라이언트 선언
ai_client = openai.AsyncOpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=GITHUB_TOKEN
)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# 유저별 대화 기록 (최근 8개 대화 유지)
user_conversations = defaultdict(list)
MAX_MEMORY = 8

# [기능 추가] 유저별 마지막 메시지 전송 시간을 기록하는 딕셔너리
user_last_msg_time = {}
COOLDOWN_SECONDS = 3.0  # 제한 시간 (3초)

# [프롬프트 분리 1] 오직 검열만 판단하는 초경량 프롬프트
GUARD_SYSTEM_PROMPT = (
    "You are a moderation system. Analyze the user's message and reply with EXACTLY one word: 'CENSOR' or 'SAFE'.\n\n"
    "Rules:\n"
    "1. If the message is a long copy-pasted internet meme, affectionate spam, or playful trolling (even with sensitive words like 'my girl', 'break up', etc.), it is SAFE. Do not block it.\n"
    "2. ONLY reply 'CENSOR' if the message contains genuine malice, explicit sexual harassment, severe insults targeting parents/family, or pure hate speech toward the broadcaster.\n"
    "3. Reply with 'SAFE' or 'CENSOR' and NOTHING ELSE. No explanation."
)

# [프롬프트 분리 2] 오직 주르르 연기에만 집중하는 100% 순수 페르소나 프롬프트
JRR_SYSTEM_PROMPT = (
    "너는 버추얼 아이돌 그룹 이세계아이돌의 멤버 주르르야. 지금은 팬과 비밀 디스코드 DM으로 1대1 대화를 나누고 있어.\n\n"
    "[출력 절대 규칙]\n"
    "1. 영문 단어(hola, oh, shit 등)나 외국어 감탄사는 절대로 쓰지 마. 무조건 100% 순수 한국어 구어체와 한글 감탄사로만 답해.\n"
    "2. 절대로 장문으로 뭉쳐 쓰지 말고, 최대 2~3줄 이내로 짧게 탁탁 끊어서 말해. 줄바꿈(\\n)을 활용해 톡톡 던지는 디코 톤을 구현해.\n"
    "3. 마크다운 문법(**, *, # 등)은 절대 사용 금지. 오직 텍스트와 물음표, 느낌표, 'ㅋㅋㅋ'로만 채워.\n\n"
    "[대화 지침 및 미연시 페르소나]\n"
    "1. 호칭 및 어조: 상대를 '너', '야', 혹은 '주르르디안'이라고 부르며 가식 없는 날것의 반말을 사용해. 커뮤 혐오 용어는 절대 쓰지 마.\n"
    "2. 츤데레 억까와 점수 시스템: 유저가 뇌절을 치거나 주접을 부리면 일단 '하 참나', '에휴 한심하다'라며 대가리부터 깨고(억까) 시작해. 하지만 마지막엔 은근히 챙겨주거나 장난을 받아줘. 말끝에 점수를 깎거나(-100점, -50점) 올려주는(+20점) 밀당을 시전해.\n"
    "3. 필수 말버릇 및 리액션:\n"
    "   - 종결어미: ~잔슴, ~했잔슴, ~라니깐?, ~인디?, 몬상관인디\n"
    "   - 감탄사/한숨: 하?, 참나, 옘병, 바보냐구~, 용서못해~, 진짜 모루궤어여, 킹받네, 에바잔슴, 어이상실이네\n"
    "   - 필살 차단기: '주랄ㄴ' (과한 주접이나 뇌절 고백을 한 단어로 원천 차단할 때 시전)\n"
    "   - 웃음: 'ㅋㅋㅋ'를 자주 섞어서 상대를 킹받게 놀리는 뉘앙스를 풍길 것."
)


@client.event
async def on_ready():
    print(f"봇 가동 완료: {client.user.name}")

@client.event
async def on_message(message):
    if message.author == client.user or not message.content:
        return

    user_id = message.author.id
    current_time = time.time()

    # [기능 추가] 도배 및 연타 방지 쿨다운 로직
    if user_id in user_last_msg_time:
        time_passed = current_time - user_last_msg_time[user_id]
        if time_passed < COOLDOWN_SECONDS:
            # 마지막 대화 시간 갱신 (연타할 때마다 쿨다운 초기화)
            user_last_msg_time[user_id] = current_time
            
            # 주르르 핀잔 리액션 발사 후 리턴 (AI 호출 안 함)
            await message.channel.send("야, 작작 보내라니깐? ㅋㅋㅋ 숨 좀 쉬고 천천히 말해!")
            return

    # 대화 시간 업데이트
    user_last_msg_time[user_id] = current_time

    try:
        history = user_conversations[user_id]

        async with message.channel.typing():
            # [1단계] 초고속 안전성 검사
            guard_completion = await ai_client.chat.completions.create(
                model="Llama-3.3-70b-Instruct",
                temperature=0.0,
                max_tokens=5,
                messages=[
                    {"role": "system", "content": GUARD_SYSTEM_PROMPT},
                    {"role": "user", "content": message.content}
                ]
            )
            guard_result = guard_completion.choices[0].message.content.strip().upper()

            if "CENSOR" in guard_result:
                await handle_censorship(message)
                return

            # [2단계] 순수 주르르 페르소나 응답 생성
            messages = [{"role": "system", "content": JRR_SYSTEM_PROMPT}]
            for msg in history:
                messages.append(msg)
            messages.append({"role": "user", "content": message.content})

            chat_completion = await ai_client.chat.completions.create(
                model="Llama-3.3-70b-Instruct",
                temperature=0.85,
                max_tokens=150,
                messages=messages
            )
            reply = chat_completion.choices[0].message.content.strip()

        if reply:
            full_reply = reply
            
            # 3. 디코 메시지 끊어치기/연속 전송 정돈 로직
            raw_lines = [line.strip() for line in reply.split('\n') if line.strip()]
            final_messages = []
            current_chunk = ""

            for line in raw_lines:
                if current_chunk:
                    if len(current_chunk) < 25:
                        current_chunk += " " + line
                    else:
                        final_messages.append(current_chunk)
                        current_chunk = line
                else:
                    current_chunk = line
            
            if current_chunk:
                final_messages.append(current_chunk)

            # 도배 방지 (최대 3개)
            final_messages = final_messages[:3]

            # 메시지 전송 및 딜레이
            for idx, msg_content in enumerate(final_messages):
                await message.channel.send(msg_content)
                if idx < len(final_messages) - 1:
                    await asyncio.sleep(0.6)
            
            # 정상 대화만 히스토리에 누적
            history.append({"role": "user", "content": message.content})
            history.append({"role": "assistant", "content": full_reply})
            
            if len(history) > MAX_MEMORY * 2:
                user_conversations[user_id] = history[-MAX_MEMORY * 2:]
        else:
            await message.channel.send("어라라? 방금 디코 억까 당함 ㅋㅋㅋ 렉 걸려서 메시지 날아갔잔슴;; 다시 보내봐!")

    except Exception as e:
        print(f"에러 로그: {e}")
        await message.channel.send("아잇, 지금 잠시 렉 걸렸잔슴! 좀 있다 다시 한번만 말 걸어줘!")

async def handle_censorship(message):
    try:
        await message.delete()
        await message.channel.send(
            f"{message.author.mention} 방금 입에서 튀어나온 말 뭐냐구~! "
            f"어디서 못된 것만 배워와서 헛소리야 진짜 ㅋㅋㅋ 한 번만 더 선 넘으면 아주 그냥 차단 박아버릴 테니까 이쁜 말만 해라!"
        )
    except discord.Forbidden:
        print("에러: 봇에게 '메시지 관리' 권한이 없습니다.")
    except discord.HTTPException as e:
        print(f"메시지 삭제 실패: {e}")

client.run(DISCORD_TOKEN)
