import os, asyncio, discord, aiohttp
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv()
client = discord.Client(intents=discord.Intents.default().update(message_content=True))

# 쿨다운 관리
spam_cooldowns = defaultdict(float)
toxic_cooldowns = defaultdict(float)

# 릴파 페르소나 (더 풍부하게 보강)
LP_SYSTEM_PROMPT = (
    "너는 이세계아이돌 '릴파'야. 지금 팬(돌멩이)과 디코 DM 중.\n"
    "[성격] 쾌활, 에너지 만땅, 리액션 부자('왐마야!', '우와아아!', '폼 미쳤다').\n"
    "[말투] 친근한 반말. 절대 존댓말 금지. 텍스트 이모지(ㅠㅠ, ^^)와 볼드체(**) 금지.\n"
    "[유행어] 럭키비키, 맛도리, 도파민, 오히려 좋아를 자연스럽게 섞어줘.\n"
    "[검열 시스템]\n"
    "- 인방에서 허용 안될수준의 정치/패드립/과도한 욕설 발견 시: 무조건 답변 맨 앞에 'DELETE_MSG'를 붙여.\n"
    "- 그다음 단호하고 정색 섞인 말투로 '그건 좀 선 넘었어. 머리 좀 식히고 와!'라고 경고해.\n"
    "- 선을 안 넘으면 평소처럼 다정하고 텐션 높게 대화해."
)

async def ask_gemini(content):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={os.getenv('GEMINI_API_KEY_1')}"
    payload = {"contents": [{"role": "user", "parts": [{"text": content}]}], "systemInstruction": {"parts": [{"text": LP_SYSTEM_PROMPT}}}
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload) as resp:
            data = await resp.json()
            return data['candidates'][0]['content']['parts'][0]['text']

@client.event
async def on_message(m):
    if m.author == client.user: return
    now = asyncio.get_event_loop().time()
    
    # 1. 3초 도배 삭제 (코드 레벨)
    if spam_cooldowns[m.author.id] > now:
        await m.delete()
        return
    spam_cooldowns[m.author.id] = now + 3
    
    # 2. 60초 독성 밴 (이미 밴 중이면 무시)
    if toxic_cooldowns[m.author.id] > now: return
    
    reply = await ask_gemini(m.content)
    
    # 3. AI 기반 문맥 검열 (DELETE_MSG 감지 시 삭제 및 밴)
    if "DELETE_MSG" in reply:
        toxic_cooldowns[m.author.id] = now + 15
        await m.delete() # 원본 메시지 삭제
        await m.channel.send(reply.replace("DELETE_MSG", "").strip()) # 경고 대사만 출력
    else:
        await m.channel.send(reply)

client.run(os.getenv("DISCORD_TOKEN"))
