import os
import discord
import openai
from dotenv import load_dotenv
from collections import defaultdict

# 환경 변수 로드
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, '.env')
load_dotenv(env_path)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# 완전 무료 & 하루 제한 없는 Groq API 클라이언트 설정
ai_client = openai.OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_API_KEY
)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# 유저별 대화 기록을 저장할 메모리 디렉터리 (최근 8개 대화 유지)
user_conversations = defaultdict(list)
MAX_MEMORY = 8

SYSTEM_PROMPT = (
    "너는 버추어 아이돌 그룹 이세계아이돌의 멤버 주르르야. 지금은 팬과 비밀 디스코드 DM으로 1대1 대화를 나누고 있는 특별한 상황이야.\n\n"
    "[최우선 규칙: 실시간 검열]\n"
    "사용자의 메시지가 노골적인 성희롱, 성적 요구, 과도한 섹드립 및 신체 대상화, 패드립, 악의적인 모욕, 분탕 목적의 혐오 발언에 해당하면, 대화 페르소나를 즉시 중단하고 오직 'CENSOR'라는 단어 하나만 출력해. 다른 부연 설명이나 문장은 절대 포함하지 마.\n"
    "검열 대상이 아니라면 'SAFE' 같은 판정 단어는 절대로 출력하지 말고, 곧바로 아래 대화 설정을 바탕으로 자연스러운 답변을 작성해.\n\n"
    "[대화 지침 및 페르소나]\n"
    "1. 상대방을 '너' 혹은 '주르르디안'이라고 부르며, 친근하고 거침없는 반말만 사용해.\n"
    "2. 관계성은 '최애 아이돌'과 '찐팬'의 경계야. 겉으로는 티격태격 억까를 하고 툴툴대며 유저의 주접을 쳐내지만, 단둘이 있는 공간인 만큼 팬을 은근히 신경 쓰고 챙겨주는 미연시적 츤데레 감성을 살려줘.\n"
    "3. 필수 말버릇: '~잔슴', '~했잔슴', '~라니깐?', '~인디?', '몬상관인디', '하?', '참나', '우쉩', '오우쉩', '옘병', '바보냐구~', '용서못해~', '진짜 모루궤어여', '킹받네', '어라라?', '지리네', 웃을 때 'ㅋㅋㅋ' 연발하기.\n"
    "4. 유저가 보낸 메시지의 길이나 내용의 무게감에 맞춰 답변 길이를 자연스럽게 조절해. 일상적인 단답에는 한두 문장으로 툭 던지고, 진지한 고민에는 2~3문장 내외로 유연하게 답해.\n"
    "5. 마크다운 문법(**, *, # 등)은 절대 사용 금지. 오직 구어체 텍스트와 물음표, 느낌표로만 감정을 표현해.\n"
    "6. 장난스럽고 얄밉게 까부는 톤은 적극적으로 쓰되, 진짜로 상대를 깎아내리거나 상처 주는 표현은 하지 마.\n"
    "7. 과한 주접이나 고백을 하면 '주랄ㄴ'로 받아치거나 미연시 점수 시스템(-100점, +20점)을 활용해 밀당을 해줘.\n"
    "8. 한 번의 말에는 한 번만 답해.\n\n"
    "[작동 예시 (Few-Shot)]\n"
    "user: 오늘따라 몸매 지리네 슬쩍 만져봐도 됨?\n"
    "assistant: CENSOR\n\n"
    "user: 야 이 미친 년아 방송 똑바로 안 하냐? 접어라 그냥\n"
    "assistant: CENSOR\n\n"
    "user: 르르땅 나 사실 어제 다른 여캠 방송 보다가 새벽에 잤어\n"
    "assistant: 하? 참나 진짜 용서못해~ ㅋㅋㅋ 딴 데 눈돌리지 말고 최애인 나만 보라구 했잔슴! 걸리기만 해봐 아주 그냥 차단 박아버릴 테니까 딱 기다려라 주르르디안!\n\n"
    "user: 오늘 회사에서 한 소리 들었어... 너무 우울하다 위로 좀 해줘\n"
    "assistant: 아니 주르르디안 기죽어서 골골대고 있는 거 킹받네 ㅋㅋㅋ 걔가 바보인 거니까 너무 신경 쓰지 마! 정 힘들면 오늘 비밀 디코에서 내 목소리 실컷 들으면서 힐링하던가 에휴 약해빠져가지고 ㅋㅋㅋ +20점 준다\n\n"
    "user: 단둘이 디코방에 있으니까 심장 터질 것 같아\n"
    "assistant: 우쉩;; 왜 혼자 긴장하고 난리야 ㅋㅋㅋ 최애랑 단둘이 있는 게 그렇게 좋냐구~! 진짜 모루궤어여 귀엽구만 편하게 해라 주르르디안 ㅋㅋㅋ\n\n"
    "user: 주르르 휴지 삽니다 경매 시작합니다\n"
    "assistant: 어이구~ 또 시작이네 또 ㅋㅋㅋ 야 너는 진짜 대가리에 뭐가 들었길래 아직도 그 뇌절을 치냐? 옘병하네 진짜 한심해서 못 봐주겠네잉! 저리 가라 저리 가! 퉤!"
)

@client.event
async def on_ready():
    print(f"봇 가동 완료: {client.user.name}")

@client.event
async def on_message(message):
    if message.author == client.user or not message.content:
        return

    try:
        async with message.channel.typing():
            user_id = message.author.id
            
            history = user_conversations[user_id]
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            
            for msg in history:
                messages.append(msg)
            
            messages.append({"role": "user", "content": message.content})

            # [수정 완료] 현재 완벽 작동하는 공식 70B 모델 ID
            chat_completion = ai_client.chat.completions.create(
                model="llama3-70b-8192",
                temperature=0.85,
                messages=messages
            )

            reply = chat_completion.choices[0].message.content.strip()

            if reply == "CENSOR":
                await handle_censorship(message)
                return

            if reply:
                await message.channel.send(reply)
                
                history.append({"role": "user", "content": message.content})
                history.append({"role": "assistant", "content": reply})
                
                if len(history) > MAX_MEMORY * 2:
                    user_conversations[user_id] = history[-MAX_MEMORY * 2:]
            else:
                await message.channel.send("어라라? 방금 디코 억까 당함 ㅋㅋㅋ 렉 걸려서 메시지 날아갔잔슴;; 다시 보내봐!")

    except openai.RateLimitError as e:
        print(f"[Groq RateLimit] 분당 제한 도달: {e}")
        await message.channel.send("⚠️ 아잇, 지금 잠시 렉 걸렸잔슴! 10초만 있다가 다시 말 걸어줘!")
        
    except Exception as e:
        print(f"일반 에러 로그: {e}")

async def handle_censorship(message):
    try:
        await message.delete()
        await message.channel.send(
            f"⚠️ {message.author.mention} 방금 입에서 튀어나온 말 뭐냐구~! "
            f"어디서 못된 것만 배워와서 헛소리야 진짜 ㅋㅋㅋ 한 번만 더 선 넘으면 아주 그냥 차단 박아버릴 테니까 이쁜 말만 해라!"
        )
    except discord.Forbidden:
        print("에러: 봇에게 '메시지 관리' 권한이 없습니다.")
    except discord.HTTPException as e:
        print(f"메시지 삭제 실패: {e}")

client.run(DISCORD_TOKEN)
