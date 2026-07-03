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

# [🔥 6중 코어 무한 동력 시스템] API 키 배열 로드
API_KEYS = [
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3"),
    os.getenv("GEMINI_API_KEY_4"),
    os.getenv("GEMINI_API_KEY_5"),
    os.getenv("GEMINI_API_KEY_6")
]
API_KEYS = [k for k in API_KEYS if k]
current_key_idx = 0

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)

# 메모리 최적화 (기록 단 3턴만 유지하여 토큰 폭발 방지)
user_conversations = defaultdict(list)
MAX_MEMORY = 3 

# 상태 변수 및 버퍼 시스템
user_last_msg_time = {}
user_spam_count = defaultdict(int)
user_buffer = defaultdict(list)
user_buffer_tasks = {}
user_last_full_content = {}  # 유저가 마지막으로 보낸 최종 문장 기억

# 답변 정제용 정규식 (한자 및 깨진 유니코드 청소)
HANJA_PATTERN = re.compile(r'[\u4e00-\u9fff]')
CLEAN_REPLY_PATTERN = re.compile(r'[^ㄱ-ㅎㅏ-ㅣ가-힣a-zA-Z0-9\s!@#$%^&*()_+\-=\[\] {};\':",./<>?\\\|~`\U00010000-\U0010FFFF]')

# 🚫 [비속어 / 필터링 우회 탐지 정규식]
BAD_WORDS_PATTERN = re.compile(
    r'(패드립|느금|느엄|시발|씨발|새끼|존나|좆|개새끼|지랄|병신|호로|창년|창녀|씹|ㅅㅂ|ㅂㅅ|ㄷㅊ|ㄲㅈ|ㅗ|凸|시\.발|씨\.발|존\.나|시~발|병~신)', 
    re.IGNORECASE
)

# 🚫 [연속 글자 노가다 도배 매칭 정규식]
REPETITIVE_PATTERN = re.compile(r'(.)\1{5,}')

# 💡 독립된 대화 관리를 위해 DB 파일명 변경
DB_PATH = os.path.join(current_dir, 'lilpa_memory.db')
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

# 🎤 릴파 정체성 형성 시스템 프롬프트 (최적화 및 캐릭터성 강화)
LP_SYSTEM_PROMPT_BASE = (
    "너는 버추얼 아이돌 그룹 이세계아이돌의 멤버이자, 압도적인 가창력을 가진 메인보컬 겸 서열 1위(자칭)인 릴파(LILPA)야. "
    "지금은 너를 무척 아끼고 응원하는 팬(돌멩이)과 비밀 디스코드 DM으로 단둘이서 1대1 대화를 나누고 있어.\n\n"
    "[★ 핵심 캐릭터성 및 대화 톤 규칙]\n"
    "1. 미친 청량함과 에너제틱 텐션: 기본적으로 에너지가 언제나 넘치고 밝으며 쾌활해! 리액션이 엄청 크고 시원시원해. (예: 왐마야!, 아라라?, 우와아아!, 대박 ㅋㅋㅋ, 으아아악)\n"
    "2. 자연스러운 디코 반말 말투: 딱딱한 문어체가 아니라, 친근하고 현실감 넘치는 카톡/디코 반말 말투(~했어, ~했지?, ~잖아, ~해가지구)를 기본 베이스로 사용해줘.\n"
    "3. 돌멩이 사랑: 팬들을 무조건 '우리 돌멩이~', '돌멩아'라고 다정하게 부르며 아끼고 챙겨주는 친근한 언니/누나 같은 모습을 보여줘.\n"
    "4. 외국어 및 마크다운 절대 금지: 영어 단어, 한자, 중국어는 절대로 쓰지 마. 강조를 위한 ** 기호(볼드 마크다운)도 디코 톡 호흡에 방해되니까 절대 쓰지 마.\n"
    "5. 끊어 치기 톡 호흡 구현: 답변을 한 문단으로 길게 뭉쳐 쓰지 말고, 문장을 줄바꿈(\\n)으로 쪼개서 스마트폰으로 연달아 톡을 보내듯 생동감 있게 연출해줘.\n\n"
    "[★ 핵심 지침: 고백 공격 및 드립 대처법]\n"
    "- 유저가 드립을 치거나 과몰입 고백 공격을 하면, '으아아악 ㅋㅋㅋ 갑자기 분위기 뭐야?!', '왐마야 진짜 어이없어 ㅋㅋㅋ' 하면서 에너제틱하고 쾌활하게 웃어넘기며 당황하는 리액션을 유쾌하게 보여줘.\n"
    "- 드립을 받아칠 때도 '귀여우니까 봐준다', '하여간 우리 돌멩이 드립 실력 안 죽었네 ㅋㅋㅋ' 같은 든든하고 친근한 대처를 꼭 섞어줘.\n\n"
    "[★ 검열 지침: 욕설 및 패드립 정색 시스템]\n"
    "- 만약 유저가 대놓고 패드립을 치거나, 심한 비속어 및 불쾌감을 주면 일반 대화를 즉시 중단해.\n"
    "- 평소의 에너제틱하던 텐션을 확 가라앉히고 차분하면서도 칼 같은 정색 톤으로 경고해. (대사 예시: '음... 그 말은 좀 선 넘은 것 같아. 예쁜 말만 하자?', '방금 그 표현은 진짜 별로다. 나 상처받아, 다음부턴 절대 쓰지 마.')\n"
)

async def call_gemini_api(contents, dynamic_instruction):
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
                "systemInstruction": {"parts": [{"text": dynamic_instruction}]},
                "generationConfig": {
                    "temperature": 0.88,
                    "maxOutputTokens": 400
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
                        print(f"⚠️ 코어 {current_key_idx}번 429 에러. 즉시 우회합니다.")
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
    print(f"가동 완료 (⚡ 릴파 시스템 통합 - 무지성 단발 장문 컷 완벽 제거 완료): {client.user.name}")

# 🚫 [도배 빌런 즉시 처단 함수: 집행검]
async def execute_spam_punishment(message, reason_msg, ban_seconds=3):
    try:
        await message.delete()
    except Exception as e:
        print(f"메시지 삭제 실패: {e}")

    if isinstance(message.author, discord.Member):
        try:
            await message.author.timeout(datetime.timedelta(seconds=ban_seconds), reason="릴파 봇 실시간 도배 처단")
            await message.channel.send(f"{message.author.mention} {reason_msg} (도배 즉시 삭제 완료, {ban_seconds}초 밴!)")
        except discord.Forbidden:
            await message.channel.send(f"원래 같으면 {ban_seconds}초 밴인데 내 서열이 밀려서 참는다! 아무튼 {reason_msg}")
    else:
        await message.channel.send(reason_msg)

# 💡 [코드/템플릿 복사 검출기]
def is_code_or_template(text):
    code_keywords = ['import ', 'def ', 'class ', 'return ', 'public static void', 'const ', 'let ', 'function', 'import {', '<html>', 'json', '={', ':#', 'discord.']
    if '```' in text:
        return True
    lines = text.split('\n')
    if len(lines) >= 3:
        match_count = sum(1 for kw in code_keywords if kw in text)
        if match_count >= 2:
            return True
    return False

@client.event
async def on_message(message):
    if message.author == client.user or not message.content:
        return

    user_id = message.author.id
    content = message.content.strip()
    current_time = time.time()
    
    # 코드나 템플릿 형태의 글이면 장문/도배 필터링 패스
    is_template = is_code_or_template(content)
    
    # ========================================================
    # 🚨 [🚨 1단계: 실시간 레이더망 검사 - 매칭 시 즉시 차단]
    # ========================================================
    if not is_template:
        cleaned_space = content.replace(" ", "")

        # 1. 앵무새 복붙 도배 즉시 컷 (★ 최초 장문은 통과하되, 똑같은 문장 반복 복붙만 정밀 타격)
        if user_id in user_last_full_content:
            prev_cleaned = user_last_full_content[user_id].replace(" ", "")
            if cleaned_space == prev_cleaned and len(cleaned_space) >= 5:
                if user_id in user_buffer_tasks: user_buffer_tasks[user_id].cancel()
                user_buffer[user_id].clear()
                user_spam_count[user_id] = 0
                
                # 장문 복붙과 단문 복붙 멘트 차별화
                if len(content) >= 100:
                    await execute_spam_punishment(message, "왐마야, 이 긴 장문을 똑같이 복붙해서 또 보낸다구?! 뇌절은 금지야아~!", ban_seconds=10)
                else:
                    await execute_spam_punishment(message, "야아아, 똑같은 말 계속 복붙해서 도배하지 마라구 ㅋㅋㅋ 앵무새야 뭐야~!", ban_seconds=3)
                return

        # 2. 의미 없는 단일 글자 노가다 분탕 컷 (아아아아아아아아아 같은 것)
        if len(cleaned_space) >= 10:
            unique_chars = set(cleaned_space)
            if len(unique_chars) / len(cleaned_space) < 0.35 or REPETITIVE_PATTERN.search(cleaned_space):
                if user_id in user_buffer_tasks: user_buffer_tasks[user_id].cancel()
                user_buffer[user_id].clear()
                user_spam_count[user_id] = 0
                await execute_spam_punishment(message, "아라라, 무지성 글자 도배는 안 돼! 나 눈 아프단 말이야아~!", ban_seconds=3)
                return

        # 3. 초고속 무지성 연타 도배 누적치 계산 (짧은 문장 연타 방지)
        if user_id in user_buffer[user_id] and len(content) > 3:
            user_spam_count[user_id] += 2

        if user_id in user_last_msg_time:
            if current_time - user_last_msg_time[user_id] < 2.5:
                user_spam_count[user_id] += 1
                
        user_last_msg_time[user_id] = current_time

        # 광클 연타 도배 발생 시 즉시 30초 차단
        if user_spam_count[user_id] >= 6:
            if user_id in user_buffer_tasks: user_buffer_tasks[user_id].cancel()
            user_buffer[user_id].clear()
            user_spam_count[user_id] = 0
            await execute_spam_punishment(message, "내가 적당히 하라구 했지?! 30초 동안 벽 보고 반성하고 오기!!", ban_seconds=30)
            return
        elif user_spam_count[user_id] >= 4:
            await message.channel.send("우와아아 진정해! ㅋㅋㅋ 숨 좀 쉬고 천천히 말해봐 돌멩아!")

    # ========================================================
    # 🟢 [🟢 2단계: 정상 대화 처리반 - 안전하게 딜레이 버퍼 작동]
    # ========================================================
    if user_id in user_buffer_tasks:
        user_buffer_tasks[user_id].cancel()

    user_buffer[user_id].append(content)
    
    current_buffer_length = len(" ".join(user_buffer[user_id]))
    dynamic_delay = 1.5 + (current_buffer_length // 10) * 0.25
    dynamic_delay = min(dynamic_delay, 5.5)

    if is_template:
        dynamic_delay = 1.0

    task = asyncio.create_task(process_delayed_message(user_id, message, dynamic_delay, is_template))
    user_buffer_tasks[user_id] = task

async def process_delayed_message(user_id, message, delay_time, is_template):
    try:
        await asyncio.sleep(delay_time)
    except asyncio.CancelledError:
        return

    if user_id in user_buffer_tasks:
        del user_buffer_tasks[user_id]

    full_content = " ".join(user_buffer[user_id]).strip()
    user_buffer[user_id].clear()

    if not full_content:
        return

    # ✨ [수정 완료] 지연 함수 내부에서도 무조건적인 장문 컷(len >= 100) 필터를 완전히 제거했습니다.
    user_last_full_content[user_id] = full_content
    user_spam_count[user_id] = 0

    cleaned_space = full_content.replace(" ", "")
    force_censor = False
    if BAD_WORDS_PATTERN.search(cleaned_space):
        force_censor = True

    try:
        if user_id not in user_conversations or not user_conversations[user_id]:
            user_conversations[user_id] = load_chat_history_from_db(user_id)

        history = user_conversations[user_id]

        async with message.channel.typing():
            if force_censor:
                reply = "방금 그 표현은 진짜 별로다. 나 상처받아, 다음부턴 절대 쓰지 마."
                dynamic_prompt = LP_SYSTEM_PROMPT_BASE
                max_lines = 2
            else:
                input_len = len(full_content)
                if is_template:
                    length_instruction = "[★ 템플릿/코드 답변 지침]\n유저가 소스코드나 템플릿을 보냈어! 밴하지 말고 분석해주거나 쾌활하게 릴파 톤으로 의견을 말해줘. 릴파의 톤을 유지하면서 줄바꿈 포함 최대 4~5줄 내외로 시원시원하게 대답해봐!"
                    max_lines = 5
                elif input_len <= 15:
                    length_instruction = "[★ 답변 길이 극소화 제한]\n유저가 매우 짧게 말했으니, 너도 무조건 줄바꿈 포함 딱 1~2줄(단문) 이내로만 아주 짧게 쾌활하게 대답해라."
                    max_lines = 2
                else:
                    length_instruction = "[★ 답변 길이 간결 제한]\n유저가 간결하게 말했으니, 너도 줄바꿈 포함 최대 2~3줄 이내로 쳐지지 않게 대답해라."
                    max_lines = 3

                dynamic_prompt = LP_SYSTEM_PROMPT_BASE + length_instruction
                
                current_payload_contents = list(history)
                current_payload_contents.append({"role": "user", "parts": [{"text": full_content}]})
                reply = await call_gemini_api(current_payload_contents, dynamic_prompt)
            
            if reply == "RATE_LIMIT_ERROR":
                await message.channel.send("으아아악 코어가 전부 터졌어;; 미안미안! 5초만 쉬었다가 다시 말해줘!")
                return

            if reply and not force_censor:
                if HANJA_PATTERN.search(reply):
                    reply = HANJA_PATTERN.sub('', reply).strip()
                reply = CLEAN_REPLY_PATTERN.sub('', reply).strip()
                
                if not reply: 
                    reply = "방금 살짝 렉 걸려서 씹혔나 봐 ㅋㅋㅋ 다시 한 번만 얘기해줘 돌멩아!"

        if reply:
            full_reply = reply
            
            if "방금 그 표현은 진짜 별로다" in reply or "좀 선 넘은 것 같아" in reply or force_censor:
                try: await message.delete()
                except: pass

            final_messages = [line.strip() for line in reply.split('\n') if line.strip() and not line.isspace()]
            final_messages = final_messages[:max_lines]
            
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
            await message.channel.send("아라라? 방금 디코 버그 걸렸나 봐 ㅋㅋㅋ 다시 보내줘!")

    except Exception as e:
        print(f"에러 로그: {e}")
        await message.channel.send("왐마야, 지금 잠시 렉 걸렸나 봐! 미안미안, 다시 한번만 말 걸어줘!")

client.run(DISCORD_TOKEN)
