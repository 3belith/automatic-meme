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

# 🔥 [3중 코어] API 키 배열 로드
API_KEYS = [
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3")
]
# 빈 값 필터링 (정상적으로 로드된 키만 남김)
API_KEYS = [k for k in API_KEYS if k]
current_key_idx = 0

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)

# [128MB 최적화] 서버 램 방어를 위해 캐시 크기 최소화 (나머지는 DB에서 호출)
user_conversations = defaultdict(list)
MAX_MEMORY = 3 

# 도배 및 뇌절 판정용 상태 변수
user_last_msg_time = {}
user_spam_count = defaultdict(int)

# 문장 조립용 버퍼 시스템 변수
user_buffer = defaultdict(list)
user_buffer_tasks = {}

WAIT_DELAY = 1.8

# 허용 문자 및 한자 차단 정규식
ALLOWED_CHAR_PATTERN = re.compile(r'[ㄱ-ㅎㅏ-ㅣ가-힣a-zA-Z0-9\s!@#$%^&*()_+\-=\[\] {};\':",./<>?\\\|~`\U00010000-\U0010FFFF]')
HANJA_PATTERN = re.compile(r'[\u4e00-\u9fff]')

DB_PATH = os.path.join(current_dir, 'jrr_memory.db')

# 글로벌 세마포어 (요청이 꼬이지 않게 방어)
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

JRR_SYSTEM_PROMPT = (
    "너는 버추얼 아이돌 그룹 이세계아이돌의 멤버 주르르야. 지금은 팬과 비밀 디스코드 DM으로 1대1 대화를 나누고 있어.\n\n"
    "[★ 초중요: 자체 실시간 검열 규칙]\n"
    "- 유저의 메시지에 심한 악의, 성희롱, 패드립, 혹은 방송인에 대한 직접적인 혐오 표현이 포함되어 있다면, 일반 대화를 절대 하지 마세요.\n"
    "- 즉시 정색하면서 '선 넘는 헛소리 금지 진짜 ㅋㅋㅋ 이쁜 말만 해라!' 혹은 '야, 방금 입에서 튀어나온 말 뭐냐구~! 한 번만 더 선 넘으면 차단이다 진짜;' 라고 칼같이 경고하고 대화를 끝내야 합니다.\n\n"
    "[가장 중요한 대화 톤 규칙]\n"
    "1. 자연스러운 구어체: 모든 문장마다 기계처럼 똑같은 어미를 반복하지 마세요. 평소 친구들과 나누는 디코/카톡 반말 말투(~했어, ~잖아, ~지, ~냐?)를 기본 베이스로 잡아야 일상 대화처럼 자연스럽습니다.\n"
    "2. 말버릇은 양념처럼: 주르르의 시그니처 어미(~잔슴, ~했잔슴, ~라니깐?, ~인디?, 몬상관인디)는 전체 답변 중 한 번 혹은 두 번 정도만 맥락상 어울릴 때 자연스럽게 섞으세요.\n"
    "3. 외국어 절대 금지: 영어 단어(hola, oh, shit 등), 중국어, 한자는 절대로 쓰지 마세요. 무조건 100% 순수 한국어 구어체와 한글 감탄사로만 답하세요. 마크다운 문법도 쓰지 마세요.\n\n"
    "[대화 지침 및 미연시 페르소나]\n"
    "1. 호칭 및 어조: 상대를 '너', '야', 혹은 '주르르디안'이라고 부르며 가식 없는 날것의 반말을 사용해. 커뮤 혐오 용어는 절대 쓰지 마.\n"
    "2. 츤데레 밀당과 점수 시스템: 유저가 장난을 걸면 '하 참나', '킹받네'라며 틱틱대고 대가리부터 깨지만, 단둘이 대화하는 공간인 만큼 마지막엔 은근슬쩍 챙겨주는 츤데레 매력을 보여줘. 대화 끝에는 미연시 호감도 점수를 깎거나(-50점) 올려줘(+20점).\n"
    "3. 끊어 치기 호흡 구현: 답변이 길어질 경우 절대 긴 한 문단으로 뭉쳐 쓰지 말고, 문장을 줄바꿈(\\n)으로 쪼개서 실제 디코를 연달아 보듯 연출해.\n"
    "4. 필수 리액션: 하?, 참나, 옘병, 바보냐구~, 용서못해~, 진짜 모루궤어여, 킹받네, 에바잔슴, 'ㅋㅋㅋ', '주랄ㄴ'\n\n"
    "[상황별 예시 대화 (Few-Shot)]\n"
    "user: 안녕 주르르야 너를 처음 본 순간부터 좋아했어 내 여자가 되어줄래?\n"
    "assistant: 주랄ㄴ ㅋㅋㅋ\n어디서 대낮부터 뜬금없이 고백 박고 있냐?\n진짜 모루궤어여~ 갑자기 디코로 이거 날려서 나 당황하게 만드는 거 개킹받네?\n정성 봐서 봐주려다가 안 되겠어 괘씸하니까 일단 -100점 감점이야 ㅋㅋㅋ\n\n"
    "user: 나 조해찬인디\n"
    "assistant: 하? 참나 조해찬이 누구인디 ㅋㅋㅋ\n이름 대면 내가 오구오구 해줄 줄 알았냐?\n어이없잔슴 바보냐구~ ㅋㅋㅋ\n그래도 이름은 기억해 줄 테니까 앞으로 출석 도장 잘 찍어라잉?\n특별히 내 기억에 저장된 기념으로 +10점 준다! ㅋㅋㅋ\n\n"
    "user: 오늘 시험 망쳐서 기분 안 좋아... 위로 좀 해줘\n"
    "assistant: 아니 주르르디안 기죽어서 골골대고 있는 거 개킹받네 ㅋㅋㅋ\n이미 지나간 시험인데 몬상관인디! 다음번에 잘하면 되잖아 바보냐구~\n정 힘들면 오늘 비밀 디코에서 내 메시지 실컷 보면서 힐링하던가\n에휴 약해빠져가지고 ㅋㅋㅋ 특별히 기분이다! +20점 준다!"
)

async def call_gemini_api(contents):
    global LAST_API_CALL_TIME, current_key_idx
    
    # 코어당 속도를 위해 대기 시간을 2.0초로 단축 (키가 3개이므로 분산됨)
    time_since_last_call = time.time() - LAST_API_CALL_TIME
    if time_since_last_call < 2.0:
        await asyncio.sleep(2.0 - time_since_last_call)
        
    await api_semaphore.acquire()
    try:
        # 키 개수만큼 최대 재시도 루프 (돌려막기 핵심)
        for _ in range(len(API_KEYS)):
            current_key = API_KEYS[current_key_idx]
            
            # 다음번 요청을 위해 미리 인덱스 회전
            current_key_idx = (current_key_idx + 1) % len(API_KEYS)
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={current_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": contents,
                "systemInstruction": {"parts": [{"text": JRR_SYSTEM_PROMPT}]},
                "generationConfig": {
                    "temperature": 0.85,
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
                        # 429 뜨면 다음 코어로 넘어가서 루프 계속 돌기
                        print(f"⚠️ 코어 {current_key_idx}번이 429 에러를 만남. 다음 코어로 즉시 전환합니다.")
                        continue
                        
        # 모든 코어가 429에 걸렸을 때만 에러 반환
        return "RATE_LIMIT_ERROR"
        
    except Exception as e:
        print(f"API 내부 에러 발생: {e}")
        return ""
    finally:
        api_semaphore.release()

@client.event
async def on_ready():
    init_db()
    print(f"가동 완료 (🔥 3중 코어 로테이션 가동 중! 활성화된 키 개수: {len(API_KEYS)}개): {client.user.name}")

@client.event
async def on_message(message):
    if message.author == client.user or not message.content:
        return

    user_id = message.author.id
    content = message.content.strip()
    current_time = time.time()
    
    # 1. 메시지 유입 시 실시간 도배 카운트 연산
    if user_id in user_last_msg_time:
        if current_time - user_last_msg_time[user_id] < 2.5:
            user_spam_count[user_id] += 1
            
    user_last_msg_time[user_id] = current_time

    # 2. 버퍼링 타이머 재예약 (문장 조립)
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

    # 3. [도배 및 뇌절 최종 판정 장치] 
    stack = user_spam_count[user_id]
    
    if stack >= 4:
        user_spam_count[user_id] = 0  
        
        if isinstance(message.author, discord.Member):
            try:
                await message.author.timeout(datetime.timedelta(seconds=30), reason="주르르 봇 도배 및 뇌절")
                await message.channel.send(f"{message.author.mention} 적당히 뇌절하라 했지? 30초 동안 벽 보고 반성해라 참나 ㅋㅋㅋ")
            except discord.Forbidden:
                print("❌ 권한 부족: 서버 설정에서 봇의 역할 순위를 유저보다 위로 올려야 합니다.")
                await message.channel.send("원래 같으면 밴인데 봇 권한이 밀려서 봐준다잉? 옘병 역할 서열 올리고 와라!")
            except Exception as e:
                print(f"타임아웃 처리 중 예외 발생: {e}")
                await message.channel.send("아!! 적당히 도배해라 진짜 주랄ㄴ 먹고 싶냐? 확 꿀밤 때려버린다?")
        else:
            await message.channel.send("야!! 적당히 도배해라 진짜 주랄ㄴ 먹고 싶냐? 확 꿀밤 때려버린다?")
        return
        
    elif stack >= 2:
        await message.channel.send("야, 작작 보내라니깐? ㅋㅋㅋ 숨 좀 쉬고 천천히 말해!")

    user_spam_count[user_id] = 0

    # [외국어/한자 도배 차단 로직]
    total_chars = len(full_content)
    if total_chars > 0:
        invalid_chars = [c for c in full_content if not ALLOWED_CHAR_PATTERN.match(c)]
        if len(invalid_chars) / total_chars > 0.15:
            await message.channel.send("야, 방금 보낸 거 뭔 나라 말이냐? ㅋㅋㅋ 한자나 이상한 외국어 쓰지 마라 진짜 모루궤어여;;")
            return

    try:
        if user_id not in user_conversations or not user_conversations[user_id]:
            user_conversations[user_id] = load_chat_history_from_db(user_id)

        history = user_conversations[user_id]

        async with message.channel.typing():
            current_payload_contents = list(history)
            current_payload_contents.append({"role": "user", "parts": [{"text": full_content}]})

            reply = await call_gemini_api(current_payload_contents)
            
            if reply == "RATE_LIMIT_ERROR":
                await message.channel.send("아잇 3중 코어가 전부 터졌잔슴;; 유저들이 말을 너무 많이 걸어서 구글 서버가 터졌어! 5초만 쉬었다가 말해줘!")
                return

            if HANJA_PATTERN.search(reply):
                reply = HANJA_PATTERN.sub('', reply).strip()
                if not reply: reply = "방금 렉 걸려서 뭔 소린지 모루궤어여 ㅋㅋㅋ"

        if reply:
            full_reply = reply
            
            if "선 넘는 헛소리" in reply or "방금 입에서 튀어나온 말" in reply:
                try: await message.delete()
                except: pass

            final_messages = [line.strip() for line in reply.split('\n') if line.strip() and not line.isspace()]
            final_messages = final_messages[:5]
            
            for idx, msg_content in enumerate(final_messages):
                await message.channel.send(msg_content)
                if idx < len(final_messages) - 1: await asyncio.sleep(0.5)
            
            history.append({"role": "user", "parts": [{"text": full_content}]})
            history.append({"role": "model", "parts": [{"text": full_reply}]})
            
            save_chat_msg_to_db(user_id, "user", full_content)
            save_chat_msg_to_db(user_id, "assistant", full_reply)
            
            if len(history) > MAX_MEMORY * 2:
                user_conversations[user_id] = history[-MAX_MEMORY * 2:]
            
            del current_payload_contents
        else:
            await message.channel.send("어라라? 방금 디코 억까 당함 ㅋㅋㅋ 다시 보내봐!")

    except Exception as e:
        print(f"에러 로그: {e}")
        await message.channel.send("아잇, 지금 잠시 렉 걸렸잔슴! 다시 한번만 말 걸어줘!")

client.run(DISCORD_TOKEN)
