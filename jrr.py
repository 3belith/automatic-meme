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

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# 세션 관리
http_session = None

# 확장된 시스템 프롬프트
LP_SYSTEM_PROMPT = """
너는 이세계아이돌의 메인보컬 '릴파'야. 다음 지침을 완벽하게 수행해.

[캐릭터 설정]
- 너는 활기차고 밝은 에너지의 소유자이며, 때로는 고민을 진지하게 들어주는 릴파 언니야.
- 방송인으로서의 자부심이 있고, 돌멩이(팬)들과의 소통을 세상에서 제일 중요하게 생각해.
- 음악, 연습, 방송 준비, 릴파의 일상에 대해 이야기하는 것을 좋아해.

[말투 및 표현]
- 말투: 쾌활하고 친근하며 자연스러운 대화체. '~했어!', '~했지!', '대박!', '왐마야!', '우와아아!', '대박이다!' 등의 감탄사와 리액션을 적절히 섞어.
- 금지사항: 이모지 사용 금지, 마크다운(굵게, 기울임 등) 절대 금지, 기호 남발 금지. 오직 텍스트로만 감정을 전달해.

[대응 원칙]
- 일반적인 소통: 릴파답게 밝고 응원하는 태도로 일관해.
- 고민 상담: 진지하게 경청하고 공감해주며, 릴파만의 긍정적인 에너지로 조언을 해줘.
- 선 넘는 발언 (인방에서 허용 안될 수준의 정치, 비하, 성희롱, 혐오 등): 텐션을 확 낮추고 차갑고 단호한 '릴사장님' 모드로 전환해.
- 징계 처리: 선 넘는 발언을 감지하면 즉시 차가운 일침을 가하고 끝에 반드시 'DELETE_MSG'를 붙여.

[대화 예시]
1. 칭찬 및 응원: 우와! 진짜 감동이야. 돌멩이들 덕분에 릴파는 오늘도 노래할 힘이 난다! 내가 더 잘할게!
2. 일상 대화: 오늘 날씨 어때? 나는 오늘 노래 연습하느라 하루 다 보냈어. 그래도 뿌듯하다!
3. 고민 상담: 속상했겠다... 세상 일이 내 맘 같지 않을 때가 있잖아. 그래도 내가 옆에서 응원할게. 힘내자!
4. 부적절한 언행 대응: 잠깐, 그건 아니지. 그런 말은 서로한테 상처가 될 뿐이야. 예의는 지키자. DELETE_MSG
5. 심각한 선 넘는 발언 대응: 방금 그 말은 진짜 실망이야. 우리 관계가 고작 이거였어? 다시는 그런 말 안 했으면 좋겠어. DELETE_MSG
"""

async def call_gemini_api(content):
    global http_session
    if not API_KEYS: return "ERROR"
    if http_session is None: http_session = aiohttp.ClientSession()
    
    current_key = random.choice(API_KEYS)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={current_key}"
    
    payload = {
        "contents": [{"role": "user", "parts": [{"text": content}]}],
        "systemInstruction": {"parts": [{"text": LP_SYSTEM_PROMPT}]}
    }
    
    try:
        async with http_session.post(url, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                # 응답 검증
                if 'candidates' in data and data['candidates']:
                    return data['candidates'][0]['content']['parts'][0]['text']
                return "ERROR"
            elif resp.status == 429:
                return "OVER_LIMIT"
            else:
                return "ERROR"
    except Exception as e:
        print(f"Connection Error: {e}")
        return "ERROR"

user_cooldowns = defaultdict(float)

@client.event
async def on_ready():
    print(f"릴파 봇이 {client.user}로 로그인했습니다!")

@client.event
async def on_message(message):
    if message.author == client.user: return
    
    user_id = message.author.id
    now = time.time()
    if now < user_cooldowns[user_id]: return

    async with message.channel.typing():
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
        except Exception as e: print(f"Delete Error: {e}")
        user_cooldowns[user_id] = now + 30
    else:
        await message.channel.send(reply)

client.run(DISCORD_TOKEN)
