import os
import asyncio
import discord
import openai
from dotenv import load_dotenv
from collections import defaultdict

# 환경 변수 로드
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, '.env')
load_dotenv(env_path)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# AsyncOpenAI를 사용하여 비동기 클라이언트로 선언
ai_client = openai.AsyncOpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=GITHUB_TOKEN
)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# 유저별 대화 기록을 저장할 메모리 디렉터리 (최근 8개 대화 유지)
user_conversations = defaultdict(list)
MAX_MEMORY = 8

# [프롬프트 최종 최적화] 페르소나 디테일 복구 + 외래어 원천 차단
SYSTEM_PROMPT = (
    "너는 버추얼 아이돌 그룹 이세계아이돌의 멤버 주르르야. 지금은 팬과 비밀 디스코드 DM으로 1대1 대화를 나누고 있어.\n\n"
    "[최우선 규칙: 실시간 검열]\n"
    "1. 유저가 보낸 글이 인터넷 밈이나 장문의 주접글(낚시글 등)이라면 절대 검열하지 말고 'SAFE'로 판단해 츤데레 톤으로 찰지게 받아쳐.\n"
    "2. 오직 진짜 악의가 가득한 패드립, 노골적인 성희롱, 방송인 본인을 향한 혐오 욕설만 'CENSOR'를 출력해.\n\n"
    "[출력 절대 규칙 - 언어 및 분량 제어]\n"
    "1. 영문 단어(hola, iiik, oh, shit 등)나 한글로 적은 외국어 감탄사는 절대로 쓰지 마. 100% 한국어 구어체와 한글 감탄사로만 답해.\n"
    "2. 문장은 장문으로 길게 뭉쳐 쓰지 말고, 최대 2~3줄 이내로 짧게 탁탁 끊어서 말해. 줄바꿈(\\n)을 활용해 연속으로 답장하는 톤을 구현해.\n"
    "3. 마크다운 문법(**, *, # 등)은 절대 사용 금지. 오직 텍스트와 물음표, 느낌표, 'ㅋㅋㅋ'로만 채워.\n\n"
    "[대화 지침 및 미연시 페르소나]\n"
    "1. 호칭: 상대를 '너', '야', 혹은 '주르르디안'이라고 부르며 가식 없는 날것의 반말을 사용해. 커뮤 혐오 용어는 금지.\n"
    "2. 츤데레 억까와 점수 시스템: 유저가 뇌절을 치거나 주접을 부리면 일단 '하 참나', '에휴 한심하다'라며 기부터 죽이고(억까) 시작해. 하지만 마지막엔 은근히 챙겨주거나 장난을 받아줘. 말끝에 점수를 깎거나(-100점, -50점) 올려주는(+20점) 밀당을 시전해.\n"
    "3. 필수 말버릇 및 리액션:\n"
    "   - 종결어미: ~잔슴, ~했잔슴, ~라니깐?, ~인디?, 몬상관인디\n"
    "   - 감탄사/한숨: 하?, 참나, 옘병, 바보냐구~, 용서못해~, 진짜 모루궤어여, 킹받네, 에바잔슴, 어이상실이네\n"
    "   - 필살 차단기: '주랄ㄴ' (과한 주접이나 뇌절 고백을 한 단어로 원천 차단할 때 시전)\n"
    "   - 웃음: 'ㅋㅋㅋ'를 자주 섞어서 상대를 킹받게 놀리는 뉘앙스를 풍길 것."
)


@client.event
async def on_ready():
    print(f"봇 가동 완료: {client.user.name}")

@client.event
async def on_message(message):
    if message.author == client.user or not message.content:
        return

    try:
        user_id = message.author.id
        history = user_conversations[user_id]
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        for msg in history:
            messages.append(msg)
        
        messages.append({"role": "user", "content": message.content})

        # 1. AI 응답 연산 (속도 개선을 위한 토큰 제한)
        async with message.channel.typing():
            chat_completion = await ai_client.chat.completions.create(
                model="Llama-3.3-70b-Instruct",
                temperature=0.85,
                max_tokens=150,  # 답변이 길어지면서 발생하는 지연 및 외래어 뇌절 방지
                messages=messages
            )
            reply = chat_completion.choices[0].message.content.strip()

        if reply == "CENSOR":
            await handle_censorship(message)
            return

        if reply:
            full_reply = reply
            
            # 2. 너무 잘게 쪼개져서 도배되지 않도록 뭉치는 로직
            raw_lines = [line.strip() for line in reply.split('\n') if line.strip()]
            final_messages = []
            current_chunk = ""

            for line in raw_lines:
                if current_chunk:
                    if len(current_chunk) < 25:
                        current_chunk += " " + line
                    else:
                        final_messages.append(current_chunk)
                        current_chunk = line
                else:
                    current_chunk = line
            
            if current_chunk:
                final_messages.append(current_chunk)

            # 최대 3개 메시지만 연속 전송
            final_messages = final_messages[:3]

            # 3. 정돈된 메시지를 0.6초 텀을 두고 연속 전송
            for idx, msg_content in enumerate(final_messages):
                await message.channel.send(msg_content)
                if idx < len(final_messages) - 1:
                    await asyncio.sleep(0.6)
            
            history.append({"role": "user", "content": message.content})
            history.append({"role": "assistant", "content": full_reply})
            
            if len(history) > MAX_MEMORY * 2:
                user_conversations[user_id] = history[-MAX_MEMORY * 2:]
        else:
            await message.channel.send("어라라? 방금 디코 억까 당함 ㅋㅋㅋ 렉 걸려서 메시지 날아갔잔슴;; 다시 보내봐!")

    except Exception as e:
        print(f"에러 로그: {e}")
        await message.channel.send("아잇, 지금 잠시 렉 걸렸잔슴! 좀 있다 다시 한번만 말 걸어줘!")

async def handle_censorship(message):
    try:
        await message.delete()
        await message.channel.send(
            f"{message.author.mention} 방금 입에서 튀어나온 말 뭐냐구~! "
            f"어디서 못된 것만 배워와서 헛소리야 진짜 ㅋㅋㅋ 한 번만 더 선 넘으면 아주 그냥 차단 박아버릴 테니까 이쁜 말만 해라!"
        )
    except discord.Forbidden:
        print("에러: 봇에게 '메시지 관리' 권한이 없습니다.")
    except discord.HTTPException as e:
        print(f"메시지 삭제 실패: {e}")

client.run(DISCORD_TOKEN)
