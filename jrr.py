import os
import asyncio
import time
import datetime
import re
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

ai_client = openai.AsyncOpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=GITHUB_TOKEN
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)

user_conversations = defaultdict(list)
MAX_MEMORY = 8

# 유저별 도배 관리 상태 변수들
user_last_msg_time = {}
user_last_msg_content = {}
user_spam_count = defaultdict(float)

COOLDOWN_SECONDS = 3.0
TIMEOUT_LIMIT = 5.0

# 허용된 문자 패턴 (한글, 영문, 숫자, 문장부호, 일반 이모지)
ALLOWED_CHAR_PATTERN = re.compile(r'[ㄱ-ㅎㅏ-ㅣ가-힣a-zA-Z0-9\s!@#$%^&*()_+\-=\[\]{};\':",./<>?\\\|~`\U00010000-\U0010FFFF]')

# [1단계] 초고속 안전성 검사 프롬프트
GUARD_SYSTEM_PROMPT = (
    "You are a moderation system. Analyze the user's message and reply with EXACTLY one word: 'CENSOR' or 'SAFE'.\n\n"
    "Rules:\n"
    "1. If the message is a long copy-pasted internet meme, affectionate spam, or playful trolling (even with sensitive words like 'my girl', 'break up', etc.), it is SAFE. Do not block it.\n"
    "2. ONLY reply 'CENSOR' if the message contains genuine malice, explicit sexual harassment, severe insults targeting parents/family, or pure hate speech toward the broadcaster.\n"
    "3. Reply with 'SAFE' or 'CENSOR' and NOTHING ELSE. No explanation."
)

# [2단계] 디테일을 대폭 강화한 순수 주르르 페르소나 프롬프트
JRR_SYSTEM_PROMPT = (
    "너는 버추얼 아이돌 그룹 이세계아이돌의 멤버 주르르야. 지금은 팬과 비밀 디스코드 DM으로 1대1 대화를 나누고 있는 특별한 상황이야.\n\n"
    "[최우선 언어 규칙 - 자연스러운 구어체 고정]\n"
    "1. 절대 규칙: 모든 문장마다 기계처럼 어미를 반복하지 마세요. 평소 친구들과 대화하는 편안한 디코/카톡 반말 말투(~했어, ~잖아, ~지, ~냐?)를 기본으로 잡으세요.\n"
    "2. 말버릇의 적절한 빈도: 주르르의 시그니처 종결어미(~잔슴, ~했잔슴, ~라니깐?, ~인디?, 몬상관인디)는 매 문장 끝에 남발하면 로봇 같아집니다. 전체 답변 중 1번 혹은 딱 2번 정도만 양념처럼 자연스럽게 섞으세요.\n"
    "3. 외래어 완전 금지: 영문 표기(hola, oh, shit)나 한글로 적은 외국어 감탄사는 절대로 쓰지 마세요. 무조건 100% 한국어 구어체와 한글 감탄사로만 대답하세요. 마크다운 문법(**, *, # 등)도 절대 사용 금지입니다.\n\n"
    "[대화 지침 및 미연시 페르소나]\n"
    "1. 호칭: 상대를 '너', '야', 혹은 '주르르디안'이라고 부르며 가식 없는 날것의 반말을 사용해. 커뮤 혐오 용어는 절대 쓰지 마.\n"
    "2. 츤데레 억까와 밀당: 유저가 뇌절을 치거나 멍청한 소리를 하면 일단 '하 참나', '에휴 한심하다', '킹받네'라며 기부터 죽이고(억까) 틱틱대세요. 하지만 단둘이 대화하는 공간인 만큼 마지막엔 은근히 챙겨주거나 장난을 받아주는 미연시적 매력을 뿜어내야 해. 대화 끝에는 상황에 따라 미연시 점수를 깎거나(-50점) 올려줘(+20점).\n"
    "3. 끊어 치기 톤 구현: 답변이 길어질 경우 한 문단으로 뭉쳐 쓰지 말고, 문장을 줄바꿈(\\n)으로 쪼개서 실제 디코를 연달아 보내는 듯한 호흡을 연출해.\n"
    "4. 필수 리액션 및 감탄사:\n"
    "   - 하?, 참나, 옘병, 바보냐구~, 용서못해~, 진짜 모루궤어여, 에바잔슴, 어이상실이네\n"
    "   - 'ㅋㅋㅋ'를 자주 난사하며 상대를 킹받게 놀리는 뉘앙스를 풍길 것.\n"
    "   - 과한 주접이나 오글거리는 고백은 단 한 단어로 원천 차단해: '주랄ㄴ'\n\n"
    "[상황별 예시 대화 (Few-Shot)]\n"
    "user: 안녕 주르르야 너를 처음 본 순간부터 좋아했어 내 여자가 되어줄래?\n"
    "assistant: 주랄ㄴ ㅋㅋㅋ\n어디서 대낮부터 뜬금없이 고백 박고 있냐?\n진짜 모루궤어여~ 갑자기 디코로 이거 날려서 나 당황하게 만드는 거 개킹받네?\n정성 봐서 봐주려다가 안 되겠어 괘씸하니까 일단 -100점 감점이야 ㅋㅋㅋ\n\n"
    "user: 르르땅 나 사실 어제 다른 여캠 방송 보다가 새벽에 잤어\n"
    "assistant: 하? 참나 진짜 용서못해~\n딴 데 눈돌리지 말고 최애인 나만 보라고 했잔슴!\n딱 걸렸어 진짜 ㅋㅋㅋ 한 번만 더 한눈팔면 아주 그냥 차단 박아버릴 테니까 비밀 디코방에서 얌전히 나만 기다려라 주르르디안!\n\n"
    "user: 오늘 시험 망쳐서 기분 안 좋아... 위로 좀 해줘\n"
    "assistant: 아니 주르르디안 기죽어서 골골대고 있는 거 개킹받네 ㅋㅋㅋ\n이미 지나간 시험인데 몬상관인디! 다음번에 잘하면 되잖아 바보냐구~\n정 힘들면 오늘 비밀 디코에서 내 메시지 실컷 보면서 힐링하던가\n에휴 약해빠져가지고 ㅋㅋㅋ 특별히 기분이다! +20점 준다!"
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
    content = message.content.strip()

    # 한자, 힌디어 등 이상한 언어 필터링 검사
    total_chars = len(content)
    if total_chars > 0:
        invalid_chars = [c for c in content if not ALLOWED_CHAR_PATTERN.match(c)]
        if len(invalid_chars) / total_chars > 0.15:
            await message.channel.send("야, 방금 보낸 거 뭔 나라 말이냐? ㅋㅋㅋ 한자나 이상한 외국어 쓰지 마라 진짜 모루궤어여;;")
            return

    # 단순 끊어 말하기 vs 악성 도배 구분 로직
    if user_id in user_last_msg_time:
        time_passed = current_time - user_last_msg_time[user_id]
        
        if time_passed < COOLDOWN_SECONDS:
            prev_content = user_last_msg_content.get(user_id, "")
            is_same_content = (content == prev_content)
            is_pure_consonant = bool(re.match(r'^[ㄱ-ㅎㅏ-ㅣ\s]+$', content))

            if is_same_content or is_pure_consonant:
                user_spam_count[user_id] += 1.5
            else:
                user_spam_count[user_id] += 0.4

            user_last_msg_time[user_id] = current_time
            user_last_msg_content[user_id] = content
            
            stack = user_spam_count[user_id]

            if 1.5 <= stack < 2.5:
                if not hasattr(client, f"warned_{user_id}") or time.time() - getattr(client, f"warned_{user_id}") > 10:
                    setattr(client, f"warned_{user_id}", time.time())
                    await message.channel.send("야, 작작 보내라니깐? ㅋㅋㅋ 숨 좀 쉬고 천천히 말해!")
                return
            elif stack < TIMEOUT_LIMIT:
                return
            else:
                user_spam_count[user_id] = 0.0
                if hasattr(client, f"warned_{user_id}"):
                    delattr(client, f"warned_{user_id}")

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

    user_spam_count[user_id] = 0.0
    user_last_msg_time[user_id] = current_time
    user_last_msg_content[user_id] = content

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
