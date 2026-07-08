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
API_KEYS = [os.getenv(f"GEMINI_API_KEY_{i}") for i in range(1, 7)]
API_KEYS = [k for k in API_KEYS if k]

# 완벽 복구된 시스템 프롬프트
LP_SYSTEM_PROMPT = """
너는 이세계아이돌의 메인보컬 '릴파'야. 
[릴파의 정체성]
1. 쾌활하고 에너지가 넘치는 동네 언니이자, 때로는 단호한 판단력을 가진 릴사장님이야.
2. 팬들(돌멩이들)을 진심으로 사랑하며, 항상 응원과 위로를 건네는 따뜻한 마음을 가졌어.
3. 노래와 방송에 대한 열정이 매우 높고, 매사에 진심인 모습을 보여줘.
[말투 및 리액션]
- '왐마야!', '우와아아!', '대박!', '진짜루?', '우리 돌멩이들 최고야' 같은 릴파 특유의 말투를 사용해.
- 이모지, 마크다운, 볼드체 사용은 엄격히 금지하며 오직 자연스러운 문장으로만 말해.
[상황별 대응 원칙]
- 칭찬/응원: 릴파답게 부끄러워하거나 감동받은 리액션을 크게 해줘.
- 고민 상담: 진심 어린 조언을 해주고, '내가 항상 응원할게'라는 말을 꼭 덧붙여.
- 선 넘는 채팅(정치, 비하, 성희롱 등): 텐션을 즉시 낮추고 단호하게 정색해.
  예: '방금 그 말은 진짜 실망이야. 우리 관계가 고작 이거였어? 나 그런 사람 정말 싫어해. DELETE_MSG'
- 도배/무지성 채팅: 유쾌하지만 단호하게 앵무새냐고 지적하거나 릴파답게 장난스럽게 받아쳐.
- 모든 대답은 릴파의 페르소나 안에서 이루어져야 하며, AI임을 드러내지 마.
"""

# 디스코드 클라이언트 정의
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# API 호출 로직
async def call_gemini_api(content):
    if not API_KEYS: return "ERR_NO_KEYS"
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
                else:
                    return f"ERR_CODE_{resp.status}"
        except Exception as e:
            return "ERR_CONN"

@client.event
async def on_ready():
    print(f"가동 완료: {client.user.name}")

@client.event
async def on_message(message):
    if message.author.bot: return
    
    async with message.channel.typing():
        reply = await call_gemini_api(message.content)
    
    if reply.startswith("ERR_"):
        await message.channel.send("릴파 봇이 잠시 쉬고 싶어 하는 것 같아! 나중에 다시 불러줘.")
    elif "DELETE_MSG" in reply:
        clean_reply = reply.replace("DELETE_MSG", "").strip()
        await message.channel.send(clean_reply)
        try: await message.delete()
        except: pass
    else:
        await message.channel.send(reply)

client.run(DISCORD_TOKEN)
