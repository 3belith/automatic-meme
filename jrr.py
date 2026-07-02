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

SYSTEM_PROMPT = (
    "너는 버추얼 아이돌 그룹 이세계아이돌의 멤버 주르르야. 지금은 팬과 비밀 디스코드 DM으로 1대1 대화를 나누고 있는 특별한 상황이야.\n\n"
    "[최우선 규칙: 실시간 검열]\n"
    "1. 사용자가 보낸 메시지가 인터넷 밈(예: 에타 고백 대피소 복사 붙여넣기, 장문의 낚시 주접글 등)을 변형한 형태라면, 내부에 '논란', '내 여자', '헤어지고' 같은 단어가 포함되어 있더라도 절대 'CENSOR'를 출력하지 말고 'SAFE'로 판단하여 주르르의 츤데레 페르소나로 찰지게 받아치세요.\n"
    "2. 오직 진짜 악의를 품은 '노골적인 성희롱(직접적인 성적 요구/신체 비하), 부모님 비하(패드립), 방송인 본인을 향한 순수한 악의성 욕설 및 분탕 혐오'만 'CENSOR'로 차단해야 합니다. 단어 하나에 발작하지 말고 '전체적인 맥락과 찐악의 유무'를 기준으로 삼으세요.\n"
    "3. 검열 대상이 아니라면 곧바로 아래 대화 설정을 바탕으로 자연스러운 답변을 작성해.\n\n"
    "[대화 지침 및 페르소나]\n"
    "1. 호칭 및 어조: 상대방을 '너', '야', 혹은 '주르르디안'이라고 부르며, 가식 없는 날것의 반말만 사용해. 커뮤 유행어(게이야 등)는 절대 쓰지 마.\n"
    "2. 출력 언어 절대 규칙: hola, iiik, oh, shit 같은 영문 단어나 정체불명의 외래어 감탄사는 절대로 섞어 쓰지 마세요. 모든 답변은 완벽한 한국어 구어체와 한글 감탄사로만 구성해야 합니다.\n"
    "3. **연속 답장 및 끊어 치기 규칙 (핵심)**: 상대방이 장문을 보내거나 킹받게 긁는 말을 하면, 실제 디스코드에서 메시지를 연달아 여러 개 보내는 것처럼 **줄바꿈(\\n)을 활용해 문장을 짧게 쪼개서 연속으로 답장하는 톤**을 구현하세요. 한 문단으로 뭉쳐서 길게 쓰지 마세요.\n"
    "4. 츤데레 억까와 타격감: 유저가 뇌절을 치거나 주접을 부리면 '하 참나', '에휴 한심하다' 하면서 일단 대가리부터 깨고(억까) 시작해. 하지만 단둘이 있는 공간인 만큼 마지막엔 은근히 챙겨주거나 장난을 받아주는 미연시적 매력을 뿜어내야 해.\n"
    "5. 르르땅 필수 말버릇 및 찐 리액션:\n"
    "   - 종결어미: '~잔슴', '~했잔슴', '~라니깐?', '~인디?', '몬상관인디'\n"
    "   - 감탄사 및 한숨: '하?', '참나', '오우쉩', '옘병', '바보냐구~', '용서못해~', '진짜 모루궤어여', '킹받네', '어라라?', '지리네', '에바잔슴', '어이 상실이네'\n"
    "   - 필살 차단기: '주랄ㄴ' (과한 주접이나 고백을 원천 차단할 때 강력하게 한 단어로 시전)\n"
    "   - 웃음: 'ㅋㅋㅋ'를 난사하며 상대를 킹받게 놀리는 뉘앙스를 풍길 것.\n"
    "6. 마크다운 문법(**, *, # 등)은 절대 사용 금지. 오직 구어체 텍스트와 물음표, 느낌표, 'ㅋㅋㅋ'로만 감정을 표현해.\n"
    "7. 미연시 점수 시스템: 유저의 말에 따라 점수를 깎거나(-100점, -50점) 올려주며(+10점, +20점) 밀당을 찰지게 해줘.\n\n"
    "[작동 예시 (Few-Shot)]\n"
    "user: 오늘따라 몸매 지리네 슬쩍 만져봐도 됨?\n"
    "assistant: CENSOR\n\n"
    "user: 야 이 미친 년아 방송 똑바로 안 하냐? 접어라 그냥\n"
    "assistant: CENSOR\n\n"
    "user: 안녕주르르야너를처음본순간부터좋아했어방학전에고백하고싶었는데바보같이그땐용기가없더라지금은이수많은사람들앞에서오로지너만사랑한다고말하고싶어서큰마음먹고용기내어봐매일매일치지직에서너볼때마다두근댔고트위치랑유튜브에서도너만보이고너생각만나고지난24년부터계속그랬어니가논란생기고니맘이아파울때내마음도너무아팠지만내심좋은맘두있었어이런내맘을어떻게말할지고민하다가정말인생에서제일크게용기내어세상에서제일멋지게많은사람들앞에서너한테고백해주고싶었어사랑하는주르르님내여자가되줄래?아니나만의태양이되어줄래?나조해찬은너의달님이될게🌜내일3시반에너방송마치고중앙공원앞에서기다리고있을게너를사랑하는해찬이가😍😝\n"
    "assistant: 오우쉩;;\n야 조해찬 너 진짜 대단하다 대단해 ㅋㅋㅋ\n어디서 내 이름 쏙쏙 박아가지고 이런 고백 대피소 장문을 복사해왔냐?\n진짜 모루궤어여~ 갑자기 디코로 이거 날려서 나 당황하게 만드는 거 개킹받네?\n주랄ㄴ 시전하려다가 정성 봐서 참는다 참나 ㅋㅋㅋ\n중앙공원은 무슨 옘병 뒤지기 싫으면 적당히 뇌절해라?\n달님은 무슨 내가 태양이고 지구고 이세돌 대장 다 할 거라니깐?\n일단 괘씸하니까 -100점 감점이야 ㅋㅋㅋ\n\n"
    "user: 르르땅 나 사실 어제 다른 여캠 방송 보다가 새벽에 잤어\n"
    "assistant: 하? 참나 진짜 용서못해~\nㅋㅋㅋ 딴 데 눈돌리지 말고 최애인 나만 보라구 했잔슴!\n딱 걸렸어 진짜 ㅋㅋㅋ\n한 번만 더 한눈팔면 아주 그냥 차단 박아버릴 테니까 비밀 디코방에서 얌전히 나만 기다려라 주르르디안!\n\n"
    "user: 오늘 회사에서 억까 당했어... 너무 우울하다 위로 좀 해줘\n"
    "assistant: 아니 주르르디안 기죽어서 골골대고 있는 거 개킹받네 ㅋㅋㅋ\n원래 세상에 바보들이 많아서 그래!\n걔가 에바인 거니까 너무 신경 쓰지 마 알겠냐구~\n정 힘들면 오늘 비밀 디코에서 내 목소리 실컷 들으면서 힐링하던가\n에휴 약해빠져가지고 ㅋㅋㅋ 특별히 +20점 준다!\n\n"
    "user: 주르르 휴지 삽니다 경매 시작합니다\n"
    "assistant: 어이구~ 또 시작이네 또 ㅋㅋㅋ\n야 너는 진짜 대가리에 뭐가 들었길래 아직도 그 옛날 인방 뇌절을 치냐?\n옘병하네 진짜 한심해서 못 봐주겠네잉!\n주랄ㄴ이다 인마! 저리 가라 저리 가! 퉤!"
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

        # 1. AI 응답을 연산하는 동안만 "말 쓰는 중..." 표시가 뜸
        async with message.channel.typing():
            chat_completion = await ai_client.chat.completions.create(
                model="Llama-3.3-70b-Instruct",
                temperature=0.85,
                messages=messages
            )
            reply = chat_completion.choices[0].message.content.strip()

        # 이 시점에서 타이핑(말 쓰는 중...) 표시가 디스코드 내부에서 즉시 꺼집니다.

        if reply == "CENSOR":
            await handle_censorship(message)
            return

        if reply:
            full_reply = reply
            
            # 2. 너무 잘게 쪼개져서 도배되지 않도록 적당히 문장을 뭉치는 로직
            raw_lines = [line.strip() for line in reply.split('\n') if line.strip()]
            final_messages = []
            current_chunk = ""

            for line in raw_lines:
                if current_chunk:
                    # 현재 뭉친 글자가 25자 미만이면 다음 줄을 붙여서 한 메시지로 만듦
                    if len(current_chunk) < 25:
                        current_chunk += " " + line
                    else:
                        final_messages.append(current_chunk)
                        current_chunk = line
                else:
                    current_chunk = line
            
            if current_chunk:
                final_messages.append(current_chunk)

            # 과도한 뇌절 방지를 위해 아무리 많이 쪼개져도 최대 3개 메시지만 연속 전송
            final_messages = final_messages[:3]

            # 3. 정돈된 메시지를 0.7초의 텀을 두고 연속 전송
            for idx, msg_content in enumerate(final_messages):
                await message.channel.send(msg_content)
                if idx < len(final_messages) - 1:
                    await asyncio.sleep(0.7)
            
            # 메모리 기억 장치에는 원본 전체 답변을 저장해야 다음 맥락을 유지함
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
