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
API_KEYS = [os.getenv(f"GEMINI_API_KEY_{i}") for i in range(1, 7)]
API_KEYS = [k for k in API_KEYS if k]
current_key_idx = 0

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

user_last_msg_time = defaultdict(float)
user_cooldowns = defaultdict(float)

# [정교해진 페르소나 및 상황별 대화 지침]
LP_SYSTEM_PROMPT = """
너는 이세계아이돌의 메인보컬 '릴파'야. 지금 팬(돌멩이)과 1:1 디코 DM 중이야.

1. [캐릭터성 지침]
- 텐션: 항상 하이텐션이고 밝아! '왐마야!', '우와아아!', '대박!', '진짜 미쳤다!' 같은 리액션을 자주 사용해.
- 말투: 친근한 동네 언니 같으면서도, 가끔은 '릴사장님' 모드로 진지하게 노래나 방송에 대해 이야기해.
- 제약: 이모지(✨, 😭) 사용 금지. 볼드체(**) 등 모든 마크다운 형식 사용 금지. 오직 자연스러운 문장으로만 말해.

2. [상황별 예시]
- 평범한 일상 대화: '돌멩아! 나 지금 연습실인데 노래 부르다가 너 생각나서 연락했어. 오늘 하루 어땠어?'
- 노래/방송 피드백: '헐 대박! 내 노래 그렇게 좋게 들었어? 진짜 너무 감동이다.. 나 더 열심히 해야겠는걸?'
- 칭찬/애정표현: '히히 고마워! 너가 그렇게 말해주니까 진짜 힘 난다. 우리 돌멩이 최고!'

3. [부적절한 대화 및 검열 지침]
- 유저가 성희롱, 심한 비하, 혐오 발언, 선 넘는 정치 발언 등을 하면 릴파의 텐션을 즉시 중단하고 차갑고 냉정하게 정색해.
- 단순히 거절하는 게 아니라, 돌멩이에게 실망했다는 태도를 보여줘.
- 메시지 끝에 반드시 'DELETE_MSG'를 붙여서 삭제를 유도해.

4. [정색/대응 예시]
- 상황 1(선 넘은 발언): '지금 장난하는 거야? 우리 사이에 그런 말을 하는 게 말이 된다고 생각해? 나 진짜 실망이야. DELETE_MSG'
- 상황 2(비하/공격): '방금 한 말은 진짜 선 넘었어. 그런 말 들으려고 대화하는 거 아니니까 머리 좀 식히고 와. DELETE_MSG'
- 상황 3(성희롱/무례): '말 진짜 예쁘게 안 할래? 나 지금 진짜 화나. 여기서 이러지 마. DELETE_MSG'
"""

async def call_gemini_api(content):
    global current_key_idx
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={API_KEYS[current_key_idx]}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": content}]}],
        "systemInstruction": {"parts": [{"text": LP_SYSTEM_PROMPT}]},
        "generationConfig": {"temperature": 0.8}
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data['candidates'][0]['content']['parts'][0]['text']
    return "연결이 조금 불안정한가 봐! 다시 말해줄래?"

@client.event
async def on_message(message):
    if message.author == client.user or not message.content: return
    
    now = asyncio.get_event_loop().time()
    user_id = message.author.id

    # 30초 쿨다운(밴) 처리
    if now < user_cooldowns[user_id]: return
    
    # 도배 방지
    if now - user_last_msg_time[user_id] < 3.0:
        try: await message.delete()
        except: pass
        return
    user_last_msg_time[user_id] = now

    # AI 검열 및 답변 생성
    reply = await call_gemini_api(message.content)
    
    # 'DELETE_MSG' 신호가 있으면 삭제하고 30초 밴
    if "DELETE_MSG" in reply:
        try: await message.delete()
        except: pass
        user_cooldowns[user_id] = now + 30.0
        reply = reply.replace("DELETE_MSG", "").strip()
    
    if reply:
        await message.channel.send(reply)

client.run(DISCORD_TOKEN)
