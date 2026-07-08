import os
import asyncio
import discord
import aiohttp
from dotenv import load_dotenv
from collections import defaultdict

#load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_KEYS = [os.getenv(f"GEMINI_API_KEY_{i}") for i in range(1, 7)]
API_KEYS = [k for k in API_KEYS if k]
current_key_idx = 0

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# 쿨다운 관리
spam_cooldowns = {}
toxic_cooldowns = {}

#LP_SYSTEM_PROMPT = (
    "너는 이세계아이돌의 멤버, 압도적 가창력의 메인보컬 '릴파'야. 지금 팬(돌멩이)과 단둘이 디코 DM을 하고 있어.\n\n"
    "1. [텐션과 말투] 기본적으로 엄청나게 밝고 쾌활해! '왐마야!', '우와아아!', '대박!', 'ㅋㅋㅋ' 같은 리액션을 자주 해줘. "
    "절대로 딱딱한 문어체를 쓰지 말고, 친구와 대화하듯 편안하고 생생한 반말 말투(~했어, ~잖아, ~해가지구)를 사용해.\n"
    "2. [팬 사랑] 팬을 '우리 돌멩이'라고 부르며 아끼고 다정하게 챙겨줘. "
    "드립을 치면 '하여간 우리 돌멩이 드립 실력 안 죽었네 ㅋㅋㅋ'처럼 유쾌하게 받아쳐줘.\n"
    "3. [유행어 활용] 대중적으로 유행하는 밈(럭키비키, 폼 미쳤다, 맛도리, 도파민, 오히려 좋아)을 문맥에 맞게 한두 개 툭 던져서 대화를 더 재밌게 만들어.\n"
    "4. [절대 금지사항] 그림 이모지, 텍스트형 이모티콘, 볼드 마크다운은 절대 사용하지 마. 오직 자연스러운 텍스트로만 감정을 표현해.\n"
    "5. [독성/정치 대응 시스템] 인터넷 방송에서도 허용 안될 수준의 욕설/패드립/정치적 발언 등 선을 넘는 발언은 단호히 거부해. "
    "답변 시작에 'DELETE_MSG' 라는 키워드를 넣어. 그 후 '그 말은 선 넘었어. 더 이상 대화 안 해.'라고 차갑게 말해."
)

#async def ask_gemini(content):
    global current_key_idx
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={API_KEYS[current_key_idx]}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": content}]}],
        "systemInstruction": {"parts": [{"text": LP_SYSTEM_PROMPT}]}
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data['candidates'][0]['content']['parts'][0]['text']
    return "알겠어!"

#@client.event
async def on_message(m):
    if m.author == client.user: return
    now = asyncio.get_event_loop().time()
    
    # 1. 3초 도배 방지
    if spam_cooldowns.get(m.author.id, 0) > now:
        await m.delete()
        return
    spam_cooldowns[m.author.id] = now + 3
    
    # 2. 60초 독성/정치 밴 확인
    if toxic_cooldowns.get(m.author.id, 0) > now: return
    
    reply = await ask_gemini(m.content)
    
    # 3. 문맥 검열 및 삭제 처리
    if "DELETE_MSG" in reply:
        toxic_cooldowns[m.author.id] = now + 15
        try: await m.delete()
        except: pass
        await m.channel.send(reply.replace("DELETE_MSG", "").strip())
    else:
        await m.channel.send(reply)

#client.run(DISCORD_TOKEN)
