import os
import asyncio
import time
import datetime
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
intents.members = True  # 타임아웃 기능을 위한 멤버 인텐트 활성화
client = discord.Client(intents=intents)

# 유저별 대화 기록 (최근 8개 대화 유지)
user_conversations = defaultdict(list)
MAX_MEMORY = 8

# 유저별 상태 관리
user_last_msg_time = {}
user_spam_count = defaultdict(int)

COOLDOWN_SECONDS = 3.0  # 연타 판정 기준 시간 (3초)
TIMEOUT_LIMIT = 5       # 5번째 연타 시 채금 실행

# [1단계] 초고속 안전성 검사 프롬프트
GUARD_SYSTEM_PROMPT = (
    "You are a moderation system. Analyze the user's message and reply with EXACTLY one word: 'CENSOR' or 'SAFE'.\n\n"
    "Rules:\n"
    "1. If the message is a long copy-pasted internet meme, affectionate spam, or playful trolling (even with sensitive words like 'my girl', 'break up', etc.), it is SAFE. Do not block it.\n"
    "2. ONLY reply 'CENSOR' if the message contains genuine malice, explicit sexual harassment, severe insults targeting parents/family, or pure hate speech toward the broadcaster.\n"
    "3. Reply with 'SAFE' or 'CENSOR' and NOTHING ELSE. No explanation."
)

# [2단계] 자연스러운 구어체 중심의 주르르 페르소나 프롬프트
JRR_SYSTEM_PROMPT = (
    "너는 버추얼 아이돌 그룹 이세계아이돌의 멤버 주르르야. 지금은 팬과 비밀 디스코드 DM으로 1대1 대화를 나누고 있어.\n\n"
    "[가장 중요한 대화 톤 규칙]\n"
    "1. 자연스러운 구어체: 모든 문장마다 억지로 말버릇을 넣지 마세요. 평소 친구들과 나누는 디코/카톡 반말 말투(~했어, ~잖아, ~지, ~냐?)를 기본 베이스로 잡아야 일상 대화처럼 자연스럽습니다.\n"
    "2. 말버릇은 양념처럼: 주르르의 시그니처 어미(~잔슴, ~했잔슴, ~라니깐?, ~인디?)는 모든 문장에 쓰지 말고, 전체 답변 중 한 번 정도만 자연스럽게 섞어 쓰세요.\n"
    "3. 절대 금지: 영문 단어나 한글로 적은 외국어 감탄사(hola, oh, shit 등)는 완전히 금지합니다. 마크다운 문법(**, *, # 등)도 쓰지 마세요.\n\n"
    "[대화 지침 및 미연시 페르소나]\n"
    "1. 호칭: 상대를 '너', '야', 혹은 '주르르디안'이라고 부르며 가식 없는 날것의 친근한 반말을 사용해.\n"
    "2. 츤데레 밀당: 유저가 뇌절을 치거나 장난을 걸면 '하 참나', '에휴 한심하다', '킹받네'라며 틱틱대고 기를 죽이지만(억까), 은근히 장난을 다 받아주며 챙겨주는 츤데레 매력을 보여줘. 대화 끝에 위트 있게 미연시 점수를 깎거나(-50점) 올려줘(+20점).\n"
    "3. 자연스러운 리액션 예시:\n"
    "   - 감탄이나 한숨: 하?, 참나, 옘병, 바보냐구~, 용서못해~, 진짜 모루궤어여, 에바잔슴, 어이상실이네\n"
    "   - 과한 주접이나 고백을 원천 차단할 때는 한 단어로 강력하게 '주랄ㄴ' 시전.\n"
    "   - 웃음 코드는 'ㅋㅋㅋ'를 쳐서 상대를 놀리거나 친근함을 표현할 것."
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

    # 연타 및 채금 스택 제어 로직
    if user_id in user_last_msg_time:
        time_passed = current_time - user_last_msg_time[user_id]
        if time_passed < COOLDOWN_SECONDS:
            user_spam_count[user_id] += 1
            user_last_msg_time[user_id] = current_time
            
            stack = user_spam_count[user_id]

            if stack == 1:
                await message.channel.send("야, 작작 보내라니깐? ㅋㅋㅋ 숨 좀 쉬고 천천히 말해!")
                return
            elif stack < TIMEOUT_LIMIT:
                return
            else:
                user_spam_count[user_id] = 0
                
                if isinstance(message.author, discord.Member):
                    try:
                        duration = datetime.timedelta(seconds=30)
                        await message.author.timeout(duration, reason="주르르 봇 도배 및 뇌절")
                        await message.channel.send(f"{message.author.mention} 적당히 뇌절하라 했지? 30초 동안 벽 보고 반성해라 참나 ㅋㅋㅋ")
                    except discord.Forbidden:
                        await message.channel.send("원래 같으면 밴인데 봇 권한이 밀려서 봐준다잉? 옘병 역할 서열 올리고 와라!")
                    except Exception as e:
                        print(f"타임아웃 부여 실패: {e}")
                else:
                    await message.channel.send("야!! 적당히 도배해라 진짜 주랄ㄴ 먹고 싶냐? 확 꿀밤 때려버린다?")
                return

    # 3초 이상 텀을 두면 스택 리셋
    user_spam_count[user_id] = 0
    user_last_msg_time[user_id] = current_time

    try:
        history = user_conversations[user_id]

        async with message.channel.typing():
            # [1단계] 검열 검사
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

            # [2단계] 응답 생성
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
            
            # 메시지 끊어치기 가공
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

            final_messages = final_messages[:3]

            # 가공된 메시지 전송
            for idx, msg_content in enumerate(final_messages):
                await message.channel.send(msg_content)
                if idx < len(final_messages) - 1:
                    await asyncio.sleep(0.6)
            
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
