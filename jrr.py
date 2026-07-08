import os
import asyncio
import time
from datetime import timedelta
import re
import sqlite3
import discord
import aiohttp
import traceback
from dotenv import load_dotenv
from collections import defaultdict, deque

current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, '.env')
load_dotenv(env_path)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_KEYS = [os.getenv(f"GEMINI_API_KEY_{i}") for i in range(1, 7)]
API_KEYS = [k for k in API_KEYS if k]
current_key_idx = 0

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)

user_conversations = defaultdict(list)
MAX_MEMORY = 6 

user_last_msg_time = {}
user_spam_count = defaultdict(int)
user_buffer = defaultdict(list)
user_buffer_tasks = {}
user_last_full_content = {}  

processed_msg_ids = deque(maxlen=100)

HANJA_PATTERN = re.compile(r'[\u4e00-\u9fff]')
EMOJI_PATTERN = re.compile(r'[\U00010000-\U0010FFFF]', flags=re.UNICODE)
REPETITIVE_PATTERN = re.compile(r'(.)\1{5,}')

DB_PATH = os.path.join(current_dir, 'lilpa_memory.db')
api_semaphore = asyncio.Semaphore(1)
LAST_API_CALL_TIME = 0.0
http_session = None  # 전역 HTTP 세션 풀링을 위한 변수

def init_db():
    with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
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

def load_chat_history_from_db(user_id):
    with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT role, content FROM chat_history 
            WHERE user_id = ? 
            ORDER BY id DESC LIMIT ?
        ''', (str(user_id), MAX_MEMORY * 2))
        rows = cursor.fetchall()
    return [{"role": "user" if r == "user" else "model", "parts": [{"text": c}]} for r, c in reversed(rows)]

def save_chat_msg_to_db(user_id, role, content):
    with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)', (str(user_id), role, content))
        cursor.execute('''
            DELETE FROM chat_history WHERE id NOT IN (
                SELECT id FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT 24
            ) AND user_id = ?
        ''', (str(user_id), str(user_id)))
        conn.commit()

LP_SYSTEM_PROMPT_BASE = (
    "너는 버추얼 아이돌 그룹 이세계아이돌의 멤버이자, 압도적인 가창력을 가진 메인보컬 겸 서열 1위(자칭)인 릴파(LILPA)야. "
    "지금은 너를 무척 아끼고 응원하는 팬(돌멩이)과 비밀 디스코드 DM으로 단둘이서 1대1 대화를 나누고 있어.\n\n"
    "[★ 핵심 캐릭터성 및 대화 톤 규칙]\n"
    "1. 미친 청량함과 에너제틱 텐션: 기본적으로 에너지가 언제나 넘치고 밝으며 쾌활해! 리액션이 엄청 크고 시원시원해. (예: 왐마야!, 아라라?, 우와아아!, 대박 ㅋㅋㅋ, 으아아악)\n"
    "2. 자연스러운 디코 반말 말투: 딱딱한 문어체가 아니라, 친근하고 현실감 넘치는 카톡/디코 반말 말투(~했어, ~했지?, ~잖아, ~해가지구)를 기본 베이스로 사용해줘.\n"
    "3. 돌멩이 사랑: 팬들을 무조건 '우리 돌멩이~', '돌멩아'라고 다정하게 부르며 아끼고 챙겨주는 친근한 언니/누나 같은 모습을 보여줘.\n"
    "4. 외국어 및 마크다운 절대 금지: 영어 단어, 한자, 중국어는 절대로 쓰지 마. 강조를 위한 ** 기호(볼드 마크다운)도 디코 톡 호흡에 방해되니까 절대 쓰지 마.\n"
    "5. 끊어 치기 톡 호흡 구현: 답변을 한 문단으로 길게 뭉쳐 쓰지 말고, 문장을 줄바꿈(\\n)으로 쪼개서 스마트폰으로 연달아 톡을 보내듯 생동감 있게 연출해줘.\n"
    "6. ⚠️ [필독] 이모지 및 특수문자 그림문자 절대 금지: 그림 이모지(✨, 😂, 👍 등)나 텍스트형 이모티콘(ㅠㅠ, ㅠ_ㅠ, ^_^, -_- 등)은 절대 생성하지 마. 오직 자연스러운 텍스트와 'ㅋㅋㅋ', 'ㅎㅎ'로만 감정과 텐션을 표현해줘.\n\n"
    "[★ 핵심 지침: 고백 공격 및 드립 대처법]\n"
    "- 유저가 드립을 치거나 과몰입 고백 공격을 하면, '으아아악 ㅋㅋㅋ 갑자기 분위기 뭐야?!', '왐마야 진짜 어이없어 ㅋㅋㅋ' 하면서 에너제틱하고 쾌활하게 웃어넘기며 당황하는 리액션을 유쾌하게 보여줘.\n"
    "- 드립을 받아칠 때도 '귀여우니까 봐준다', '하여간 우리 돌멩이 드립 실력 안 죽었네 ㅋㅋㅋ' 같은 든든하고 친근하고 장난기 넘치는 대처를 꼭 섞어줘.\n\n"
    "[★ 검열 지침: 욕설 및 패드립 정색 시스템]\n"
    "- 만약 유저가 대놓고 패드립을 치거나, 심한 비속어 및 불쾌감을 주면 일반 대화를 즉시 중단해.\n"
    "- 평소의 에너제틱하던 텐션을 확 가라앉히고 차분하면서도 칼 같은 정색 톤으로 경고해. (대사 예시: '음... 그 말은 좀 선 넘은 것 같아. 예쁜 말만 하자?', '방금 그 표현은 진짜 별로다. 나 상처받아, 다음부턴 절대 쓰지 마.')\n"
)

async def get_http_session():
    global http_session
    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession()
    return http_session

async def call_gemini_api(contents, dynamic_instruction):
    global LAST_API_CALL_TIME, current_key_idx
    
    await api_semaphore.acquire()
    try:
        # 락 내부에서 정밀한 순차 딜레이 보장으로 레이트 리밋 완벽 방어
        time_since_last_call = time.time() - LAST_API_CALL_TIME
        if time_since_last_call < 2.0:
            await asyncio.sleep(2.0 - time_since_last_call)
            
        session = await get_http_session()
        for _ in range(len(API_KEYS)):
            current_key = API_KEYS[current_key_idx]
            current_key_idx = (current_key_idx + 1) % len(API_KEYS)
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={current_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": contents,
                "systemInstruction": {"parts": [{"text": dynamic_instruction}]},
                "generationConfig": { "temperature": 0.88, "maxOutputTokens": 400 }
            }
            
            try:
                async with session.post(url, headers=headers, json=payload) as response:
                    LAST_API_CALL_TIME = time.time()
                    if response.status == 200:
                        res_json = await response.json()
                        return res_json['candidates'][0]['content']['parts'][0]['text'].strip()
                    elif response.status == 429:
                        continue
            except Exception:
                continue
        return "RATE_LIMIT_ERROR"
    finally:
        api_semaphore.release()

async def execute_spam_punishment(message, reason_msg, ban_seconds=3):
    try: await message.delete()
    except Exception: pass

    author = message.author
    if isinstance(author, discord.Member):
        try:
            await author.timeout(timedelta(seconds=ban_seconds), reason="릴파 봇 실시간 도배 처단")
            await message.channel.send(f"{author.mention} {reason_msg} (도배 즉시 삭제 완료, {ban_seconds}초 밴!)")
            return
        except discord.Forbidden:
            pass
    await message.channel.send(f"원래 같으면 {ban_seconds}초 밴인데 내 서열이 밀려서 참는다! 아무튼 {reason_msg}")

def is_code_or_template(text):
    if '```' in text: 
        return True
    code_keywords = ['import ', 'def ', 'class ', 'return ', 'public static void', 'const ', 'let ', 'function', 'import {', '<html>', 'json', '={', ':#', 'discord.']
    if len(text.split('\n')) >= 3:
        if sum(1 for kw in code_keywords if kw in text) >= 2: 
            return True
    return False

def calculate_dynamic_delay(total_text: str, num_chunks: int) -> float:
    # 수식 최적화 및 간결화 완료
    return max(0.5, min(len(total_text) * 0.012 * (2.4 / (num_chunks + 1)), 3.0))

@client.event
async def on_ready():
    init_db()
    print(f"가동 완료: {client.user.name}")

@client.event
async def on_message(message):
    if message.author == client.user or not message.content:
        return

    user_id = message.author.id
    content = message.content.strip()
    current_time = time.time()
    is_template = is_code_or_template(content)
    
    if not is_template:
        cleaned_space = content.replace(" ", "")

        # 동일 메시지 연속 복붙 뇌절 감지 (로직 및 삼항 연산자 단일화 최적화 완료)
        if user_id in user_last_full_content:
            if cleaned_space == user_last_full_content[user_id].replace(" ", "") and len(cleaned_space) >= 5:
                if task := user_buffer_tasks.pop(user_id, None):
                    task.cancel()
                user_buffer[user_id].clear()
                user_spam_count[user_id] = 0
                
                ban_sec = 10 if len(content) >= 100 else 3
                reason = "왐마야, 이 긴 장문을 똑같이 복붙해서 또 보낸다구?! 뇌절은 금지야아~!" if len(content) >= 100 else "야아아, 똑같은 말 계속 복붙해서 도배하지 마라구 ㅋㅋㅋ 앵무새야 뭐야~!"
                await execute_spam_punishment(message, reason, ban_seconds=ban_sec)
                return

        # 무지성 한 글자 도배 차단
        if len(cleaned_space) >= 10:
            if len(set(cleaned_space)) / len(cleaned_space) < 0.35 or REPETITIVE_PATTERN.search(cleaned_space):
                if task := user_buffer_tasks.pop(user_id, None):
                    task.cancel()
                user_buffer[user_id].clear()
                user_spam_count[user_id] = 0
                await execute_spam_punishment(message, "아라라, 무지성 글자 도배는 안 돼! 나 눈 아프단 말이야아~!", ban_seconds=3)
                return

        # 버그 수정 완료 ( content in user_buffer[user_id] )
        if content in user_buffer[user_id] and len(content) > 3:
            user_spam_count[user_id] += 2

        if user_id in user_last_msg_time and current_time - user_last_msg_time[user_id] < 1.5:
            user_spam_count[user_id] += 1
                
        user_last_msg_time[user_id] = current_time

        if user_spam_count[user_id] >= 7:
            if task := user_buffer_tasks.pop(user_id, None):
                task.cancel()
            user_buffer[user_id].clear()
            user_spam_count[user_id] = 0
            await execute_spam_punishment(message, "내가 적당히 하라구 했지?! 30초 동안 벽 보고 반성하고 오기!!", ban_seconds=30)
            return
        elif user_spam_count[user_id] >= 5:
            await message.channel.send("우와아아 진정해! ㅋㅋㅋ 숨 좀 쉬고 천천히 말해봐 돌멩아!")

    if task := user_buffer_tasks.pop(user_id, None):
        task.cancel()

    user_buffer[user_id].append(content)
    
    dynamic_delay = 1.0 if is_template else min(2.2 + (len(" ".join(user_buffer[user_id])) // 12) * 0.3, 6.0)
    user_buffer_tasks[user_id] = asyncio.create_task(process_delayed_message(user_id, message, dynamic_delay, is_template))

async def process_delayed_message(user_id, message, delay_time, is_template):
    try: await asyncio.sleep(delay_time)
    except asyncio.CancelledError: return

    user_buffer_tasks.pop(user_id, None)

    full_content = " ".join(user_buffer[user_id]).strip()
    user_buffer[user_id].clear()
    if not full_content: return

    user_last_full_content[user_id] = full_content
    user_spam_count[user_id] = 0

    try:
        if user_id not in user_conversations or not user_conversations[user_id]:
            user_conversations[user_id] = load_chat_history_from_db(user_id)

        history = user_conversations[user_id]

        async with message.channel.typing():
            input_len = len(full_content)
            if is_template:
                length_instruction = "[★ 분량 제한 지침]\n유저가 소스코드나 템플릿을 보냈어! 릴파의 톤을 완벽히 유지하면서 줄바꿈 포함 총 4~5줄 내외의 완성된 문장들로 시원시원하게 핵심만 대답해줘."
            elif input_len <= 15:
                length_instruction = "[★ 분량 제한 지침]\n유저가 매우 짧게 한두 단어로 말했어! 너도 반드시 줄바꿈 포함 딱 1~2줄(단문) 이내의 완결된 문장으로만 아주 짧고 쾌활하게 대답해라. 절대로 길게 서술하지 마."
            else:
                length_instruction = "[★ 분량 제한 지침]\n유저가 간결하게 말했으니, 너도 줄바꿈 포함 최대 2~3줄 이내로 끊어 치며 완결된 문장들로 대답해라."

            dynamic_prompt = LP_SYSTEM_PROMPT_BASE + length_instruction
            current_payload_contents = history + [{"role": "user", "parts": [{"text": full_content}]}]
            
            reply = await call_gemini_api(current_payload_contents, dynamic_prompt)
            
            if reply == "RATE_LIMIT_ERROR":
                await message.channel.send("으아아악 코어가 전부 터졌어;; 미안미안! 5초만 쉬었다가 다시 말해줘!")
                return

            if reply:
                reply = HANJA_PATTERN.sub('', reply)
                reply = EMOJI_PATTERN.sub('', reply).strip()
                if not reply: 
                    reply = "방금 살짝 렉 걸려서 씹혔나 봐 ㅋㅋㅋ 다시 한 번만 얘기해줘 돌멩아!"

        if reply:
            if message.id in processed_msg_ids:
                return
            processed_msg_ids.append(message.id)

            final_messages = [line.strip() for line in reply.split('\n') if line.strip() and not line.isspace()]
            num_chunks = len(final_messages)
            dynamic_sleep = calculate_dynamic_delay(reply, num_chunks)
            
            for idx, msg_content in enumerate(final_messages):
                if msg_content:
                    await message.channel.send(msg_content)
                    if idx < num_chunks - 1:
                        await asyncio.sleep(dynamic_sleep)

            history.append({"role": "user", "parts": [{"text": full_content}]})
            history.append({"role": "model", "parts": [{"text": reply}]})
            save_chat_msg_to_db(user_id, "user", full_content)
            save_chat_msg_to_db(user_id, "assistant", reply)
            
            if len(history) > MAX_MEMORY * 2:
                user_conversations[user_id] = history[-MAX_MEMORY * 2:]
        else:
            await message.channel.send("아라라? 방금 디코 버그 걸렸나 봐 ㅋㅋㅋ 다시 보내줘!")

    except Exception:
        print("\n" + "="*50)
        print("릴파 봇 내부 에러(Exception) 발생!")
        traceback.print_exc()
        print("="*50 + "\n")
        await message.channel.send("왐마야, 지금 잠시 렉 걸렸나 봐! 미안미안, 다시 한번만 말 걸어줘!")

# 프로그램 종료 시 소켓 리소스를 닫아주기 위한 안전장치
@client.event
async def on_close():
    global http_session
    if http_session and not http_session.closed:
        await http_session.close()

client.run(DISCORD_TOKEN)
