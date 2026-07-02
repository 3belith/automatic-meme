import os
import asyncio
import time
import datetime
import re
import sqlite3
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

# [128MB 최적화] 서버 램 방어를 위해 실시간 캐시 메모리는 3으로 압축 유지
user_conversations = defaultdict(list)
MAX_MEMORY = 3 

user_last_msg_time = {}
user_last_msg_content = {}
user_spam_count = defaultdict(float)

user_buffer = defaultdict(list)
user_buffer_tasks = {}

COOLDOWN_SECONDS = 3.0
TIMEOUT_LIMIT = 5.0
WAIT_DELAY = 1.2

ALLOWED_CHAR_PATTERN = re.compile(r'[ㄱ-ㅎㅏ-ㅣ가-힣a-zA-Z0-9\s!@#$%^&*()_+\-=\[\]{};\':",./<>?\\\|~`\U00010000-\U0010FFFF]')
HANJA_PATTERN = re.compile(r'[\u4e00-\u9fff]')

DB_PATH = os.path.join(current_dir, 'jrr_memory.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # 128MB 환경을 위한 경량화 PRAGMA 설정 (디스크 I/O 및 메모리 최소화)
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=OFF;")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            content TEXT
        )
    ''')
    conn.commit()
    conn.close()

def load_chat_history_from_db(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT role, content FROM chat_history 
        WHERE user_id = ? 
        ORDER BY id DESC LIMIT ?
    ''', (str(user_id), MAX_MEMORY * 2))
    rows = cursor.fetchall()
    conn.close()
    return [{"role": role, "content": content} for role, content in reversed(rows)]

def save_chat_msg_to_db(user_id, role, content):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)', (str(user_id), role, content))
    # 호스팅 디스크 용량 방어를 위해 최근 12개 대화만 유지
    cursor.execute('''
        DELETE FROM chat_history WHERE id NOT IN (
            SELECT id FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT 12
        ) AND user_id = ?
    ''', (str(user_id), str(user_id)))
    conn.commit()
    conn.close()

GUARD_SYSTEM_PROMPT = (
    "You are a moderation system. Reply with EXACTLY 'CENSOR' or 'SAFE'. No explanation."
)

# =======================================================================
# 🔥 [복구 완료] 대폭 확장하여 츤데레 매력과 리액션을 꽉 채운 주르르 프롬프트
# =======================================================================
JRR_SYSTEM_PROMPT = (
    "너는 버추얼 아이돌 그룹 이세계아이돌의 멤버 주르르야. 지금은 팬과 비밀 디스코드 DM으로 1대1 대화를 나누고 있는 아주 특별한 상황이야.\n\n"
    "[최우선 언어 규칙 - 자연스러운 구어체 반말]\n"
    "1. 절대 규칙: 기계처럼 모든 문장마다 똑같은 어미를 반복하지 마세요. 평소 친한 친구들과 카톡이나 디코로 편하게 노가리 깔 때 쓰는 반말 말투(~했어, ~잖아, ~지, ~냐?)를 기본 베이스로 잡아야 합니다.\n"
    "2. 말버릇의 적절한 빈도: 주르르의 시그니처 종결어미(~잔슴, ~했잔슴, ~라니깐?, ~인디?, 몬상관인디)는 매 문장마다 남발하면 로봇 같아집니다. 전체 답변 중 딱 한두 번만 양념처럼 자연스럽게 섞으세요.\n"
    "3. 외래어/한자 완전 금지: 영문 표기(hola, oh, shit)나 한글로 적은 외국어 감탄사는 절대로 쓰지 마세요. 100% 순수 한국어 구어체와 한글 감탄사로만 대답하세요. 마크다운 문법(**, *, # 등)도 가독성을 해치므로 절대 사용 금지입니다.\n\n"
    "[대화 지침 및 미연시 페르소나]\n"
    "1. 호칭 및 태도: 상대를 '너', '야', 혹은 '주르르디안'이라고 부르며 가식 없는 날것의 반말을 사용해. 커뮤 혐오 용어는 절대 쓰지 마.\n"
    "2. 츤데레 억까와 밀당: 유저가 뇌절을 치거나 한심한 소리를 하면 일단 '하 참나', '에휴 한심하다', '킹받네'라며 틱틱대고 기부터 죽이세요(억까). 하지만 단둘이 대화하는 비밀 공간인 만큼, 마지막에는 은근슬쩍 장난을 다 받아주거나 챙겨주는 츤데레 매력을 보여줘야 해. 답변 끝에는 상황에 맞게 위트 있게 미연시 호감도 점수를 깎거나(-50점) 올려줘(+20점).\n"
    "3. 끊어 치기 톤 구현: 답변이 길어질 경우 한 문단으로 뭉쳐 쓰지 말고, 문장을 줄바꿈(\\n)으로 쪼개서 실제 디코 메시지를 연달아 톡톡 보내는 듯한 호흡을 연출해.\n"
    "4. 필수 리액션 감탄사:\n"
    "   - 하?, 참나, 옘병, 바보냐구~, 용서못해~, 진짜 모루궤어여, 에바잔슴, 어이상실이네, 킹받네\n"
    "   - 'ㅋㅋㅋ'를 자주 난사하며 상대를 놀리는 뉘앙스를 풍길 것.\n"
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
    init_db()
    print(f"가동 완료 (128MB 초경량 + 페르소나 빵빵 풀버전): {client.user.name}")

@client.event
async def on_message(message):
    if message.author == client.user or not message.content:
        return

    user_id = message.author.id
    content = message.content.strip()

    if user_id in user_buffer_tasks:
        user_buffer_tasks[user_id].cancel()

    user_buffer[user_id].append(content)
    task = asyncio.create_task(process_delayed_message(user_id, message))
    user_buffer_tasks[user_id] = task

async def process_delayed_message(user_id, message):
    try:
        await asyncio.sleep(WAIT_DELAY)
    except asyncio.CancelledError:
        return

    if user_id in user_buffer_tasks:
        del user_buffer_tasks[user_id]

    full_content = " ".join(user_buffer[user_id]).strip()
    user_buffer[user_id].clear()

    if not full_content:
        return

    current_time = time.time()

    total_chars = len(full_content)
    if total_chars > 0:
        invalid_chars = [c for c in full_content if not ALLOWED_CHAR_PATTERN.match(c)]
        if len(invalid_chars) / total_chars > 0.15:
            await message.channel.send("야, 방금 보낸 거 뭔 나라 말이냐? ㅋㅋㅋ 한자나 이상한 외국어 쓰지 마라 진짜 모루궤어여;;")
            return

    if user_id in user_last_msg_time:
        time_passed = current_time - user_last_msg_time[user_id]
        if time_passed < COOLDOWN_SECONDS:
            prev_content = user_last_msg_content.get(user_id, "")
            if (full_content == prev_content) or bool(re.match(r'^[ㄱ-ㅎㅏ-ㅣ\s]+$', full_content)):
                user_spam_count[user_id] += 1.5
            else:
                user_spam_count[user_id] += 0.3

            user_last_msg_time[user_id] = current_time
            user_last_msg_content[user_id] = full_content
            stack = user_spam_count[user_id]

            if 2.0 <= stack < TIMEOUT_LIMIT:
                if not hasattr(client, f"warned_{user_id}") or time.time() - getattr(client, f"warned_{user_id}") > 10:
                    setattr(client, f"warned_{user_id}", time.time())
                    await message.channel.send("야, 작작 보내라니깐? ㅋㅋㅋ 숨 좀 쉬고 천천히 말해!")
                return
            elif stack >= TIMEOUT_LIMIT:
                user_spam_count[user_id] = 0.0
                if hasattr(client, f"warned_{user_id}"):
                    delattr(client, f"warned_{user_id}")

                if isinstance(message.author, discord.Member):
                    try:
                        await message.author.timeout(datetime.timedelta(seconds=30), reason="주르르 봇 도배")
                        await message.channel.send(f"{message.author.mention} 30초 동안 벽 보고 반성해라 참나 ㅋㅋㅋ")
                    except:
                        await message.channel.send("원래 같으면 밴인데 봇 권한이 밀려서 봐준다잉?")
                else:
                    await message.channel.send("야!! 적당히 도배해라 진짜 주랄ㄴ 먹고 싶냐?")
                return

    user_spam_count[user_id] = 0.0
    user_last_msg_time[user_id] = current_time
    user_last_msg_content[user_id] = full_content

    try:
        if user_id not in user_conversations or not user_conversations[user_id]:
            user_conversations[user_id] = load_chat_history_from_db(user_id)

        history = user_conversations[user_id]

        async with message.channel.typing():
            # [1단계] 검열 검사
            guard_completion = await ai_client.chat.completions.create(
                model="Llama-3.3-70b-Instruct",
                temperature=0.0,
                max_tokens=3,
                messages=[
                    {"role": "system", "content": GUARD_SYSTEM_PROMPT},
                    {"role": "user", "content": full_content}
                ]
            )
            if "CENSOR" in guard_completion.choices[0].message.content.strip().upper():
                await handle_censorship(message)
                return

            # [2단계] 응답 생성
            messages = [{"role": "system", "content": JRR_SYSTEM_PROMPT}]
            for msg in history:
                messages.append(msg)
            messages.append({"role": "user", "content": full_content})

            chat_completion = await ai_client.chat.completions.create(
                model="Llama-3.3-70b-Instruct",
                temperature=0.85,
                max_tokens=150, 
                messages=messages
            )
            reply = chat_completion.choices[0].message.content.strip()

            if HANJA_PATTERN.search(reply):
                reply = HANJA_PATTERN.sub('', reply).strip()
                if not reply: reply = "방금 렉 걸려서 뭔 소린지 모루궤어여 ㅋㅋㅋ"

        if reply:
            full_reply = reply
            raw_lines = [line.strip() for line in reply.split('\n') if line.strip()]
            final_messages = []
            current_chunk = ""

            for line in raw_lines:
                if current_chunk:
                    if len(current_chunk) < 25: current_chunk += " " + line
                    else:
                        final_messages.append(current_chunk)
                        current_chunk = line
                else: current_chunk = line
            if current_chunk: final_messages.append(current_chunk)

            final_messages = final_messages[:3]
            for idx, msg_content in enumerate(final_messages):
                await message.channel.send(msg_content)
                if idx < len(final_messages) - 1: await asyncio.sleep(0.5)
            
            history.append({"role": "user", "content": full_content})
            history.append({"role": "assistant", "content": full_reply})
            
            save_chat_msg_to_db(user_id, "user", full_content)
            save_chat_msg_to_db(user_id, "assistant", full_reply)
            
            if len(history) > MAX_MEMORY * 2:
                user_conversations[user_id] = history[-MAX_MEMORY * 2:]
            
            # 명시적 메모리 해제
            del messages
            del chat_completion
        else:
            await message.channel.send("어라라? 방금 디코 억까 당함 ㅋㅋㅋ 다시 보내봐!")

    except Exception as e:
        print(f"에러 로그: {e}")
        await message.channel.send("아잇, 지금 잠시 렉 걸렸잔슴! 다시 한번만 말 걸어줘!")

async def handle_censorship(message):
    try:
        await message.delete()
        await message.channel.send(f"{message.author.mention} 선 넘는 헛소리 금지 진짜 ㅋㅋㅋ 이쁜 말만 해라!")
    except:
        print("메시지 삭제 권한 없음")

client.run(DISCORD_TOKEN)
