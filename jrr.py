import os
import random
import asyncio
import discord
import aiohttp
import time
from dotenv import load_dotenv
from collections import defaultdict

# 환경 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(current_dir, '.env'))

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
# API 키 리스트 관리
API_KEYS = [os.getenv(f"GEMINI_API_KEY_{i}") for i in range(1, 7)]
API_KEYS = [k for k in API_KEYS if k]

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

http_session = None
# 호출 횟수 카운터 추가
api_call_count = 0 

LP_SYSTEM_PROMPT = """
(이전과 동일한 릴파 페르소나 - 생략)
"""

async def call_gemini_api(content):
    global http_session, api_call_count
    if not API_KEYS: return "ERROR"
    if http_session is None: http_session = aiohttp.ClientSession()
    
    current_key = random.choice(API_KEYS)
    api_call_count += 1
    print(f"[DEBUG] API 호출 횟수: {api_call_count}회") # 터미널에서 호출 횟수 확인
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={current_key}"
    
    payload = {
        "contents": [{"role": "user", "parts": [{"text": content}]}],
        "systemInstruction": {"parts": [{"text": LP_SYSTEM_PROMPT}]}
    }
    
    try:
        async with http_session.post(url, json=payload) as resp:
            data = await resp.json()
            if resp.status == 200:
                return data['candidates'][0]['content']['parts'][0]['text']
            elif resp.status == 429:
                print(f"[!] 쿼터 초과 경고: API 키 사용량 제한 도달")
                return "OVER_LIMIT"
            else:
                print(f"[!] API 에러 발생: {resp.status} - {data}")
                return "ERROR"
    except Exception as e:
        print(f"[!] Connection Error: {e}")
        return "ERROR"

@client.event
async def on_message(message):
    # 1. 봇 메시지 무조건 차단
    if message.author.bot: return
    # 2. 멘션이 없거나 내가 호출되지 않았을 때 무시하도록 설정 가능 (필요 시)
    
    user_id = message.author.id
    
    async with message.channel.typing():
        reply = await call_gemini_api(message.content)
    
    if reply == "OVER_LIMIT":
        await message.channel.send("지금 돌멩이들이랑 너무 많이 대화해서 릴파 목이 다 쉬었어!")
    elif reply == "ERROR":
        await message.channel.send("릴파 뇌가 잠시 과부하 됐어!")
    elif "DELETE_MSG" in reply:
        await message.channel.send(reply.replace("DELETE_MSG", "").strip())
        try: await message.delete()
        except: pass
    else:
        await message.channel.send(reply)

client.run(DISCORD_TOKEN)
