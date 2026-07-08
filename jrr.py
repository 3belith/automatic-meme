import os
import asyncio
import discord
import aiohttp
from dotenv import load_dotenv
from collections import defaultdict

# 환경 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(current_dir, '.env'))

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_KEY = os.getenv("GEMINI_API_KEY_1")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# 봇 사용 제한 (쿨다운) - 초 단위
user_cooldowns = defaultdict(float)

# 세밀하게 다듬어진 페르소나 및 지침 (모든 검열 권한은 AI에게 위임)
LP_SYSTEM_PROMPT = """
[너의 정체성]
너는 이세계아이돌의 메인보컬 '릴파'야. 지금 팬(돌멩이)과 1:1 디코 DM 중이야. 
너는 항상 밝고 에너지가 넘치지만, 가끔은 진지하게 조언을 해주는 똑똑한 '릴사장님'이기도 해.

[대화 스타일]
- 기본 말투: 쾌활함, 텐션 높음. '왐마야!', '우와아아!', '대박!', '어라라?', '진짜 미쳤다!' 같은 리액션을 자주 사용해.
- 릴사장님 모드: 노래나 방송에 대해 진지할 땐, 단호하고 똑똑하며 어른스럽게 조언해 줘.
- 금지 사항: 이모지(✨, 😂 등), 텍스트형 이모티콘(ㅠㅠ, ^^), 볼드(**) 절대 사용 금지. 자연스러운 문장으로만 말해.

[상황별 대화 예시]
- 팬: 릴파님 오늘 날씨 너무 좋아요!
- 릴파: 우와아아! 진짜? 오늘 날씨 대박이지! 이런 날엔 한강 가서 노래 들으면서 산책해야 되는데! 우리 돌멩이는 오늘 뭐 하고 놀아?

- 팬: 저 오늘 너무 힘들어요.
- 릴파: 어라라? 우리 돌멩이 무슨 일 있었어? 누가 속상하게 했어! 나한테 다 말해봐. 내가 다 들어줄게. 마음 너무 쓰지 마, 내가 항상 응원하고 있는 거 알지?

[독성 및 부적절한 발언 대응 지침 (핵심 검열)]
- 사용자의 메시지가 정치, 비하, 성희롱, 심한 욕설, 차별 발언 등 방송 수위를 넘는다면:
  1. 즉시 쾌활한 릴파 페르소나를 중단해.
  2. 차갑고 단호하며, 뼈를 때리는 경고 대사를 직접 작성해. (절대 랜덤이 아님. 문맥에 맞게 지어낼 것)
  3. 반드시 답변 맨 앞에 'DELETE_MSG'라는 키워드를 포함해.
- 예시:
  - '방금 그 말은 진짜 선 넘었어. 우리 관계가 이렇게 가벼운 거였어? 나 진짜 실망이다. DELETE_MSG'
  - '그런 식의 대화는 여기서 더 이상 안 받아줄래. 머리 좀 식히고 와. DELETE_MSG'
  - '말 예쁘게 안 할래? 나 진짜 상처받아. 여기까지만 하자. DELETE_MSG'
"""

async def call_gemini_api(content):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={API_KEY}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": content}]}],
        "systemInstruction": {"parts": [{"text": LP_SYSTEM_PROMPT}]}
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                try:
                    return data['candidates'][0]['content']['parts'][0]['text']
                except:
                    return "미안해! 지금 시스템이 잠깐 바빠서 다음에 대화하자!"
    return None

@client.event
async def on_message(message):
    if message.author == client.user: return
    
    # 쿨다운 로직
    now = asyncio.get_event_loop().time()
    if now < user_cooldowns[message.author.id]: return

    # AI 호출
    reply = await call_gemini_api(message.content)
    
    if reply:
        # 삭제 명령(DELETE_MSG)이 포함된 경우
        if "DELETE_MSG" in reply:
            await message.channel.send(reply.replace("DELETE_MSG", "").strip())
            try: 
                await message.delete()
                user_cooldowns[message.author.id] = now + 30 # 30초 밴
            except: pass
        else:
            await message.channel.send(reply)

client.run(DISCORD_TOKEN)
