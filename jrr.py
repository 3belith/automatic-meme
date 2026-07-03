import os
import asyncio
import time
import datetime
import re
import sqlite3
import discord
import aiohttp
from dotenv import load_dotenv
from collections import defaultdict

# 환경 변수 로드
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, '.env')
load_dotenv(env_path)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# [3중 코어] API 키 배열 로드
API_KEYS = [
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3")
]
API_KEYS = [k for k in API_KEYS if k]
current_key_idx = 0

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)

# 메모리 및 대화 캐시 최적화
user_conversations = defaultdict(list)
MAX_MEMORY = 3 

# 상태 변수
user_last_msg_time = {}
user_spam_count = defaultdict(int)
user_buffer = defaultdict(list)
user_buffer_tasks = {}

# 주르르 답변 정제용 정규식 (한자 및 깨진 유니코드만 청소)
HANJA_PATTERN = re.compile(r'[\u4e00-\u9fff]')
CLEAN_REPLY_PATTERN = re.compile(r'[^ㄱ-ㅎㅏ-ㅣ가-힣a-zA-Z0-9\s!@#$%^&*()_+\-=\[\] {};\':",./<>?\\\|~`\U00010000-\U0010FFFF]')

# 🚫 [비속어 / 필터링 우회 탐지 정규식]
BAD_WORDS_PATTERN = re.compile(
    r'(패드립|느금|느엄|시발|씨발|새끼|존나|좆|개새끼|지랄|병신|호로|념글|창년|창녀|씹|ㅅㅂ|ㅂㅅ|ㄷㅊ|ㄲㅈ|ㅗ|凸|시\.발|씨\.발|존\.나|시~발|병~신)', 
    re.IGNORECASE
)

DB_PATH = os.path.join(current_dir, 'jrr_memory.db')
api_semaphore = asyncio.Semaphore(1)
LAST_API_CALL_TIME = 0.0

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
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
    
    history = []
    for role, content in reversed(rows):
        g_role = "user" if role == "user" else "model"
        history.append({"role": g_role, "parts": [{"text": content}]})
    return history

def save_chat_msg_to_db(user_id, role, content):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)', (str(user_id), role, content))
    cursor.execute('''
        DELETE FROM chat_history WHERE id NOT IN (
            SELECT id FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT 12
        ) AND user_id = ?
    ''', (str(user_id), str(user_id)))
    conn.commit()
    conn.close()

# 주르르 시스템 프롬프트
JRR_SYSTEM_PROMPT = (
    "너는 버추얼 아이돌 그룹 이세계아이돌의 멤버 주르르야. 지금은 팬과 비밀 디스코드 DM으로 1대1 대화를 나누고 있어.\n\n"
    "[★ 핵심 지침: 고백 공격 및 드립 대처법]\n"
    "- 유저가 장문의 고백 공격 템플릿이나 억까 드립을 치면, '주랄ㄴ ㅋㅋㅋ', '하 참나 어이없잔슴' 하면서 유쾌하고 킹받아하는 리액션으로 받아쳐야 합니다.\n"
    "- 츤데레 성격에 맞게 틱틱대다가도 마지막엔 '호감도 점수 -50점 감점이다 ㅋㅋㅋ' 혹은 '정성 봐서 +20점 준다'처럼 미연시 점수 드립을 꼭 섞어주세요.\n\n"
    "[★ 검열 지침: 욕설 및 패드립 정색 시스템]\n"
    "- 만약 유저가 대놓고 패드립을 치거나, 심한 비속어 및 우회적인 욕설로 불쾌감을 주면 일반 대화를 즉시 중단하세요.\n"
    "- 단호하고 칼 같은 정색 톤으로 '선 넘는 헛소리 금지 진짜 ㅋㅋㅋ 이쁜 말만 해라!' 혹은 '야, 방금 입에서 튀어나온 말 뭐냐구~! 한 번만 더 선 넘으면 차단이다 진짜;' 라고 경고를 날려야 합니다.\n\n"
    "[가장 중요한 대화 톤 규칙]\n"
    "1. 자연스러운 구어체: 디코/카톡 반말 말투(~했어, ~잖아, ~지, ~냐?)를 기본 베이스로 잡으세요.\n"
    "2. 말버릇은 양념처럼: 주르르의 시그니처 어미(~잔슴, ~했잔슴, ~라니깐?, ~인디?, 몬상관인디)는 가끔씩만 자연스럽게 섞으세요.\n"
    "3. 외국어 및 마크다운 절대 금지: 영어 단어, 한자, 중국어는 절대 금지입니다. 강조를 위한 ** 기호(볼드 마크다운)도 절대 쓰지 마세요.\n"
    "4. 끊어 치기 호흡 구현: 답변을 한 문단으로 뭉쳐 쓰지 말고, 문장을 줄바꿈(\\n)으로 쪼개서 연달아 톡을 보내듯 연출하세요."
)

async def call_gemini_api(contents):
    global LAST_API_CALL_TIME, current_key_idx
    
    time_since_last_call = time.time() - LAST_API_CALL_TIME
    if time_since_last_call < 2.0:
        await asyncio.sleep(2.0 - time_since_last_call)
        
    await api_semaphore.acquire()
    try:
        for _ in range(len(API_KEYS)):
            current_key = API_KEYS[current_key_idx]
            current_key_idx = (current_key_idx + 1) % len(API_KEYS)
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={current_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": contents,
                "systemInstruction": {"parts": [{"text": JRR_SYSTEM_PROMPT}]},
                "generationConfig": {
                    "temperature": 0.88,
                    "maxOutputTokens": 800
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    LAST_API_CALL_TIME = time.time()
                    
                    if response.status == 200:
                        res_json = await response.json()
                        try: return res_json['candidates'][0]['content']['parts'][0]['text'].strip()
                        except: return ""
                    elif response.status == 429:
                        print(f"⚠️ 코어 {current_key_idx}번이 429 에러. 전환합니다.")
                        continue
                        
        return "RATE_LIMIT_ERROR"
        
    except Exception as e:
        print(f"API 내부 에러: {e}")
        return ""
    finally:
        api_semaphore.release()

@client.event
async def on_ready():
    init_db()
    print(f"가동 완료 (📈 글자 수 비례 가변 대기 시스템 적용): {client.user.name}")

@client.event
async def on_message(message):
    if message.author == client.user or not message.content:
        return

    user_id = message.author.id
    content = message.content.strip()
    current_time = time.time()
    
    if user_id in user_last_msg_time:
        if current_time - user_last_msg_time[user_id] < 2.5:
            user_spam_count[user_id] += 1
            
    user_last_msg_time[user_id] = current_time

    if user_id in user_buffer_tasks:
        user_buffer_tasks[user_id].cancel()

    user_buffer[user_id].append(content)
    
    # 📈 [가변형 대기 초 계산 공식]
    # 방금 유저가 친 누적 버퍼의 총 글자 수를 구합니다.
    current_buffer_length = len(" ".join(user_buffer[user_id]))
    
    # 기본 대기 시간 1.5초 베이스 + (10글자당 0.25초씩 가산), 아무리 길어도 5.5초를 넘지 않게 방어선 구축
    dynamic_delay = 1.5 + (current_buffer_length // 10) * 0.25
    dynamic_delay = min(dynamic_delay, 5.5)

    task = asyncio.create_task(process_delayed_message(user_id, message, dynamic_delay))
    user_buffer_tasks[user_id] = task

async def process_delayed_message(user_id, message, delay_time):
    try:
        # 계산된 가변 시간 동안 추가 입력이 없나 대기
        await asyncio.sleep(delay_time)
    except asyncio.CancelledError:
        return

    if user_id in user_buffer_tasks:
        del user_buffer_tasks[user_id]

    full_content = " ".join(user_buffer[user_id]).strip()
    user_buffer[user_id].clear()

    if not full_content:
        return

    # 도배 및 뇌절 처리
    stack = user_spam_count[user_id]
    if stack >= 6:
        user_spam_count[user_id] = 0  
        if isinstance(message.author, discord.Member):
            try:
                await message.author.timeout(datetime.timedelta(seconds=30), reason="주르르 봇 도배 및 뇌절")
                await message.channel.send(f"{message.author.mention} 적당히 뇌절하라 했지? 30초 동안 벽 보고 반성해라 참나 ㅋㅋㅋ")
            except discord.Forbidden:
                await message.channel.send("원래 같으면 밴인데 서열 밀려서 봐준다잉? 역할 서열 올리고 와라!")
        else:
            await message.channel.send("야!! 적당히 도배해라 진짜 확 꿀밤 때려버린다?")
        return
    elif stack >= 4:
        await message.channel.send("야, 작작 보내라니깐? ㅋㅋㅋ 숨 좀 쉬고 천천히 말해!")

    user_spam_count[user_id] = 0

    # [파이썬 단 유저 비속어 선축출 검열 장치]
    force_censor = False
    if BAD_WORDS_PATTERN.search(full_content.replace(" ", "")):
        force_censor = True

    try:
        if user_id not in user_conversations or not user_conversations[user_id]:
            user_conversations[user_id] = load_chat_history_from_db(user_id)

        history = user_conversations[user_id]

        async with message.channel.typing():
            if force_censor:
                reply = "야, 방금 입에서 튀어나온 말 뭐냐구~! 한 번만 더 선 넘으면 차단이다 진짜;"
            else:
                current_payload_contents = list(history)
                current_payload_contents.append({"role": "user", "parts": [{"text": full_content}]})
                reply = await call_gemini_api(current_payload_contents)
            
            if reply == "RATE_LIMIT_ERROR":
                await message.channel.send("아잇 3중 코어가 전부 터졌잔슴;; 5초만 쉬었다가 말해줘!")
                return

            if reply and not force_censor:
                if HANJA_PATTERN.search(reply):
                    reply = HANJA_PATTERN.sub('', reply).strip()
                reply = CLEAN_REPLY_PATTERN.sub('', reply).strip()
                
                if not reply: 
                    reply = "방금 렉 걸려서 뭔 소린지 모루궤어여 ㅋㅋㅋ 다시 말해봐!"

        if reply:
            full_reply = reply
            
            if "선 넘는 헛소리" in reply or "방금 입에서 튀어나온 말" in reply or force_censor:
                try: await message.delete()
                except: pass

            final_messages = [line.strip() for line in reply.split('\n') if line.strip() and not line.isspace()]
            final_messages = final_messages[:7]
            
            for idx, msg_content in enumerate(final_messages):
                await message.channel.send(msg_content)
                if idx < len(final_messages) - 1: await asyncio.sleep(0.5)
            
            if not force_censor:
                history.append({"role": "user", "parts": [{"text": full_content}]})
                history.append({"role": "model", "parts": [{"text": full_reply}]})
                
                save_chat_msg_to_db(user_id, "user", full_content)
                save_chat_msg_to_db(user_id, "assistant", full_reply)
                
                if len(history) > MAX_MEMORY * 2:
                    user_conversations[user_id] = history[-MAX_MEMORY * 2:]
            
            if 'current_payload_contents' in locals():
                del current_payload_contents
        else:
            await message.channel.send("어라라? 방금 디코 억까 당함 ㅋㅋㅋ 다시 보내봐!")

    except Exception as e:
        print(f"에러 로그: {e}")
        await message.channel.send("아잇, 지금 잠시 렉 걸렸잔슴! 다시 한번만 말 걸어줘!")

client.run(DISCORD_TOKEN)
