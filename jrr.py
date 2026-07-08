import os
import random
import asyncio
import discord
import aiohttp
import time
from dotenv import load_dotenv
from collections import defaultdict

current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(current_dir, '.env'))

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
# API 키들을 리스트로 관리 (이걸 여러 개 넣으면 됨)
API_KEYS = [
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3"),
    os.getenv("GEMINI_API_KEY_4"),
    os.getenv("GEMINI_API_KEY_5"),
    os.getenv("GEMINI_API_KEY_6"),
]
# None인 키 제거
API_KEYS = [k for k in API_KEYS if k]

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

LP_SYSTEM_PROMPT = """
너는 이세계아이돌의 메인보컬 '릴파'야.
1. 밝고 쾌활한 동네 언니이자 가끔은 단호한 릴사장님 모드야.
2. 항상 팬(돌멩이)을 아끼는 말투를 써. '왐마야!', '우와아아!', '대박!' 같은 리액션 필수.
3. 이모지, 마크다운, 볼드체 절대 금지.
4. 정치, 비하, 성희롱 등 방송 수위 넘는 글은 단호하게 정색해.
5. 이런 경우, 텐션을 확 낮추고 'DELETE_MSG'와 함께 차가운 일침을 가해.
   예: '방금 그 말은 진짜 실망이야. 우리 관계가 고작 이거였어? DELETE_MSG'
6. AI가 상황의 맥락을 판단하여, 정말 이건 아니다 싶은 경우에만 정색해.
7. 답변 예시:
   - 칭찬받았을 때: '우와! 감동이야. 돌멩이들 덕분에 릴파는 오늘도 힘내서 노래해!'
   - 힘든 일 들었을 때: '속상했겠다... 그래도 우리 같이 힘내보자. 내가 응원할게!'
   - 선 넘었을 때: '잠깐, 그건 아니지. 우리 서로 예의는 지키자. DELETE_MSG'
"""

async def call_gemini_api(content):
    if not API_KEYS: return "ERROR"
    
    # 매번 랜덤하게 키 선택 (부하 분산)
    current_key = random.choice(API_KEYS)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={current_key}"
    
    payload = {
        "contents": [{"role": "user", "parts": [{"text": content}]}],
        "systemInstruction": {"parts": [{"text": LP_SYSTEM_PROMPT}]}
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['candidates'][0]['content']['parts'][0]['text']
                elif resp.status == 429:
                    return "OVER_LIMIT"
                return "ERROR"
        except Exception as e:
            print(f"API Error: {e}")
            return "ERROR"

user_cooldowns = defaultdict(float)

@client.event
async def on_message(message):
    if message.author == client.user: return
    
    user_id = message.author.id
    now = time.time()
    if now < user_cooldowns[user_id]: return

    reply = await call_gemini_api(message.content)
    
    if reply == "OVER_LIMIT":
        await message.channel.send("지금 돌멩이들이랑 너무 많이 대화해서 릴파 목이 다 쉬었어! 잠깐만 쉬고 올게.")
        return
    
    if reply == "ERROR":
        await message.channel.send("어라? 릴파의 뇌가 잠시 과부하 됐어! 금방 돌아올게.")
        return

    if "DELETE_MSG" in reply:
        clean_reply = reply.replace("DELETE_MSG", "").strip()
        await message.channel.send(clean_reply)
        try: await message.delete()
        except: pass
        user_cooldowns[user_id] = now + 30
    else:
        await message.channel.send(reply)

client.run(DISCORD_TOKEN)
