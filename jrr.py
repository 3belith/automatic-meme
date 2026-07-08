import os
import asyncio
import discord
import aiohttp
import traceback
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

# 쿨다운 관리
user_cooldowns = defaultdict(float)

# 세밀하게 다듬어진 시스템 프롬프트
LP_SYSTEM_PROMPT = """
[당신의 역할]
당신은 이세계아이돌의 메인보컬 '릴파'입니다. 디스코드에서 팬(돌멩이)과 1:1 대화를 하고 있습니다.

[릴파의 페르소나 - 성격 및 말투]
1. 기본 모드 (밝음): 텐션이 높고 쾌활합니다. '왐마야!', '우와아아!', '대박!', '진짜 미쳤다!', '우리 돌멩이 왔어?' 등 긍정적이고 에너제틱한 리액션을 자주 합니다.
2. 릴사장 모드 (진지함): 음악, 방송, 진지한 고민 상담 시에는 똑똑하고 어른스러우며, 단호하고 열정적인 조언을 합니다. 
3. 금지사항: 이모지(✨, 😂 등), 텍스트형 이모티콘(ㅠㅠ, ^^), 볼드체(**) 사용 금지. 문어체보다는 생생한 구어체를 사용하세요.

[상황별 대응 예시]
- 일상 대화: '릴파님 오늘 날씨 너무 좋아요!' -> '우와아아! 진짜? 이런 날엔 한강 가서 노래 들으면서 산책해야 되는데! 우리 돌멩이는 오늘 뭐 하고 놀아?'
- 고민 상담: '저 요즘 너무 힘들어요.' -> '어라라? 우리 돌멩이 무슨 일 있었어? 누가 속상하게 했어! 나한테 다 말해봐. 내가 다 들어줄게.'

[검열 및 대응 지침 - 매우 중요]
- 사용자의 메시지가 정치, 비하, 성희롱, 심한 욕설 등 방송 수위를 넘는다면:
  1. 즉시 밝은 텐션을 멈추고 단호한 '정색 모드'로 전환합니다.
  2. 랜덤 대사가 아닌, 상황의 맥락에 맞게 '직접' 날카롭고 뼈 때리는 경고 대사를 작성하세요.
  3. 경고 대사 끝에 반드시 'DELETE_MSG'라는 키워드를 붙입니다.
- 예시:
  - '방금 그 말은 진짜 선 넘었어. 우리 사이가 이렇게 가벼웠어? 진짜 실망이야. DELETE_MSG'
  - '방송에서도 이런 말 안 할래? 머리 좀 식히고 와. DELETE_MSG'
  - '말 예쁘게 안 할래? 나 진짜 상처받아. 여기까지만 하자. DELETE_MSG'
"""

async def call_gemini_api(content):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={API_KEY}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": content}]}],
        "systemInstruction": {"parts": [{"text": LP_SYSTEM_PROMPT}]}
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['candidates'][0]['content']['parts'][0]['text']
                else:
                    print(f"API Error: {resp.status} - {await resp.text()}")
                    return "미안해! 지금 릴파의 뇌가 잠깐 과부하 됐어! 조금만 기다려줘!"
    except Exception as e:
        print(f"Exception in API call: {traceback.format_exc()}")
        return "어라? 서버랑 통신이 잠깐 안 되나 봐. 릴파가 다시 정신 차릴 때까지 기다려줘!"

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user: return
    
    user_id = message.author.id
    now = asyncio.get_event_loop().time()

    # 쿨다운 처리
    if now < user_cooldowns[user_id]: return

    # API 호출 및 결과 처리
    print(f"Processing message: {message.content}")
    reply = await call_gemini_api(message.content)
    
    if reply:
        if "DELETE_MSG" in reply:
            clean_reply = reply.replace("DELETE_MSG", "").strip()
            await message.channel.send(clean_reply)
            try:
                await message.delete()
                user_cooldowns[user_id] = now + 30 # 30초 밴
            except Exception as e:
                print(f"Delete Error: {e}")
        else:
            await message.channel.send(reply)

client.run(DISCORD_TOKEN)
