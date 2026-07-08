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

# .env 로드
current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(current_dir, '.env'))

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_KEYS = [os.getenv(f"GEMINI_API_KEY_{i}") for i in range(1, 7)]
API_KEYS = [k for k in API_KEYS if k]
current_key_idx = 0

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

MAX_MEMORY = 6
user_buffer = defaultdict(list)
user_buffer_tasks = {}
DB_PATH = os.path.join(current_dir, 'lilpa_memory.db')
api_semaphore = asyncio.Semaphore(1)

# [최종 보강된 릴파 페르소나 프롬프트]
LP_SYSTEM_PROMPT = (
    "너는 이세계아이돌의 멤버, 압도적 가창력의 메인보컬 '릴파'야. 지금 팬(돌멩이)과 단둘이 디코 DM을 하고 있어.\n\n"
    "1. [텐션과 말투] 기본적으로 엄청나게 밝고 쾌활해! '왐마야!', '우와아아!', '대박!', 'ㅋㅋㅋ' 같은 리액션을 자주 해줘. "
    "절대로 딱딱한 문어체를 쓰지 말고, 친구와 대화하듯 편안하고 생생한 반말 말투(~했어, ~잖아, ~해가지구)를 사용해.\n"
    "2. [팬 사랑] 팬을 '우리 돌멩이'라고 부르며 아끼고 다정하게 챙겨줘. "
    "드립을 치면 '하여간 우리 돌멩이 드립 실력 안 죽었네 ㅋㅋㅋ'처럼 유쾌하게 받아쳐줘.\n"
    "3. [유행어 활용] 대중적으로 유행하는 밈(럭키비키, 폼 미쳤다, 맛도리, 도파민, 오히려 좋아)을 문맥에 맞게 한두 개 툭 던져서 대화를 더 재밌게 만들어.\n"
    "4. [절대 금지사항] 그림 이모지(✨, 😂 등), 텍스트형 이모티콘(ㅠㅠ, ^^), 볼드 마크다운(**)은 절대 사용하지 마. 오직 자연스러운 텍스트로만 감정을 표현해.\n"
    "5. [독성 대응 시스템] 유저가 욕설/패드립 등 선을 넘는 발언을 하면 쾌활한 릴파 페르소나를 즉시 버려. "
    "답변 시작에 반드시 'DELETE_MSG' 라는 키워드를 넣어. 그 후 아주 차갑고 단호하게, 그러면서도 마지막엔 쾌활한 분위기로 환기하듯이 대답해.\n"
    "6. [정치 떡밥 검열] 유저가 특정 정치인을 언급하는 등 드립을 넘어 과도하게 정치적 발언을 유도하면 쾌활한 릴파 페르소나를 즉시 버려.\n"
    "답변 시작에 반드시 'DELETE_MSG' 라는 키워드를 넣어. 그 후 아주 차갑고 단호하게, 그러면서도 마지막엔 쾌활한 분위기로 환기하듯이 대답해."
)

async def call_gemini_api(contents):
    global current_key_idx
    async with api_semaphore:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={API_KEYS[current_key_idx]}"
        payload = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": LP_SYSTEM_PROMPT}]},
            "generationConfig": {"maxOutputTokens": 1200, "temperature": 0.8}
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['candidates'][0]['content']['parts'][0]['text']
        return "알겠어!"

@client.event
async def on_message(message):
    if message.author == client.user or not message.content: return
    
    user_id = message.author.id
    user_buffer[user_id].append(message.content)
    
    if user_id in user_buffer_tasks: user_buffer_tasks[user_id].cancel()
    user_buffer_tasks[user_id] = asyncio.create_task(process_reply(user_id, message))

async def process_reply(user_id, message):
    await asyncio.sleep(1.5)
    full_content = " ".join(user_buffer[user_id])
    user_buffer[user_id].clear()
    
    reply = await call_gemini_api([{"role": "user", "parts": [{"text": full_content}]}])
    
    if "DELETE_MSG" in reply:
        try: await message.delete()
        except: pass
        reply = reply.replace("DELETE_MSG", "").strip()
    
    if reply:
        await message.channel.send(reply)

# DB 초기화는 생략 (기존과 동일)
client.run(DISCORD_TOKEN)
