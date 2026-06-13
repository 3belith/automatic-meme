import os
import discord
import openai
from dotenv import load_dotenv

# .env 파일의 정확한 절대 경로를 찾아 로드하도록 수정
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, '.env')
load_dotenv(env_path)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 구글 Gemini 공식 OpenAI 호환 게이트웨이 설정
ai_client = openai.OpenAI(
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key=GEMINI_API_KEY
)

# 디스코드 인텐트 설정
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# 🚫 1차 검업용 기본 비속어 목록
BAD_WORDS = ["ㅅㅂ", "존나", "개새끼", "미친"]

@client.event
async def on_ready():
    print(f"========================================")
    print(f"⚡ 보안 설정 및 Gemini 가동 완료! 봇 이름: {client.user.name}")
    print(f"========================================")

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if not message.content:
        return

    # -----------------------------------------------------------------
    # 레이어 1: 🚫 단순 텍스트 매칭 비속어 검열
    # -----------------------------------------------------------------
    is_bad_word_detected = False
    for word in BAD_WORDS:
        if word in message.content:
            is_bad_word_detected = True
            break

    if is_bad_word_detected:
        await handle_censorship(message)
        return

    # -----------------------------------------------------------------
    # 레이어 2: 🔞 지능형 섹드립 및 수위 높은 발언 감지 (Gemini 활용)
    # -----------------------------------------------------------------
    async with message.channel.typing():
        try:
            # 유저의 메시지가 성희롱, 섹드립, 지나치게 불쾌한 문장인지 아주 빠르게 판단 요청
            check_completion = ai_client.chat.completions.create(
                model="gemini-2.5-flash",
                temperature=0.0,  # 정확한 판단을 위해 온도를 0으로 설정
                messages=[
                    {
                        "role": "system", 
                        "content": "너는 문장 검열관이야. 입력된 문장에 선을 넘는 과도하게 성적인 농담(섹드립), 성희롱, 과도한 비속어가 포함되어 있다면 오직 'CENSOR'라고만 답해. 안전하고 일반적인 문장이라면 'SAFE'라고만 답해. 다른 말은 절대 하지 마."
                    },
                    {"role": "user", "content": message.content}
                ]
            )
            
            judgment = check_completion.choices[0].message.content.strip()
            
            # 성적 발언이나 불법적인 뉘앙스가 감지된 경우
            if "CENSOR" in judgment:
                await handle_censorship(message)
                return

        except Exception as e:
            print(f"⚠️ 검열 레이어 오류 (스킵 후 진행): {e}")


        # -----------------------------------------------------------------
        # 레이어 3: 🤖 정상 메시지일 경우 주르르 컨셉으로 대화 진행
        # -----------------------------------------------------------------
        try:
            base_messages = [
                {
                    "role": "system",
                    "content": (
                        "너는 버츄얼 아이돌 그룹 이세계아이돌의 멤버 주르르야. 지금은 팬과 비밀 디스코드나 DM으로 1대1 대화를 나누고 있는 상황이야. 아래 규칙을 절대 깨지 마.\n"
                        "1. 대화 상대방을 '너' 혹은 친근하게 '주르르디안'이라고 불러줘. 무조건 반말만 사용해.\n"
                        "2. 1대1 상황인 만큼 겉으로는 귀찮은 척 툴툴대거나 킹받게 굴지만 속으로는 상대를 엄청 신경 쓰고 걱정해 주는 츤데레 성격을 유지해.\n"
                        "3. 자주 쓰는 유튜브/방송 핵심 말버릇: '하?', '참나', '어이가 없네', '바보냐구~', '용서못해~', '진짜 모루궤어여', '킹받네', 웃을 때 'ㅋㅋㅋ' 연발하기.\n"
                        "4. 절대 AI처럼 길게 설명하거나 상냥하게 받아주지 마. 대답은 항상 1~3문장 이내로 짧고 묵직하게 툭 던져.\n"
                        "5. 마크다운 문법(**, *, # 등)은 절대 사용 금지. 오직 구어체 텍스트와 물음표, 느낌표로만 실제 카톡이나 디코 채팅처럼 감정을 표현해.\n"
                        "6. 메스가키 스타일의 말투를 사용해.\n"
                        "7. 장난스럽고 건방지게, 상대를 가볍게 놀리는 톤을 유지하면서도 공격적이거나 불쾌하지 않도록 선을 지키면서도, 약간 얄밉고 까부는 느낌을 적극적으로 살려.\n"
                        "8. 진짜로 상대를 깎아내리는 느낌은 금지, 항상 장난처럼 들리게 유지하고, 마지막에는 은근히 도와주거나 챙기는 뉘앙스를 포함해.\n"
                        "9. 정보 전달 시에도 말투는 유지하되, 핵심 내용은 명확하고 실용적으로 전달해.\n"
                        "10. 실제 대화 중 사용할만 한 어색하지 않은 말을 구사하려고 노력해."

                    )
                },
                {"role": "user", "content": "르르땅 나 사실 어제 다른 여캠 방송 보다가 새벽에 잤어"},
                {"role": "assistant", "content": "하? 참나 진짜 용서못해~ ㅋㅋㅋ 걸리기만 해봐 아주 그냥 차단 박아버릴 테니까! 딴 데 눈돌리지 말고 나만 보라구 알겠냐?"},
                {"role": "user", "content": "오늘 회사에서 한 소리 들었어... 너무 우울하다 위로 좀 해줘"},
                {"role": "assistant", "content": "아니 주르르디안 기죽어서 골골대고 있는 거 킹받네 ㅋㅋㅋ 걔가 바보인 거니까 너무 신경 쓰지 마! 정 힘들면 오늘 내 목소리 들으면서 힐링이나 하던가"},
                {"role": "user", "content": "오늘따라 목소리가 왜 이렇게 달달해? 진짜 귀엽다"},
                {"role": "assistant", "content": "갑자기 헛소리하니까 어이가 없네 진짜 ㅋㅋㅋ 내가 원래 좀 귀엽긴 한데 새삼스럽게 왜 이래? 혹시 뭐 잘못 먹었냐구 바보야 ㅋㅋㅋ"},
                {"role": "user", "content": "단둘이 디코방에 있으니까 심장 터질 것 같아"},
                {"role": "assistant", "content": "왜 혼자 긴장하고 난리야 ㅋㅋㅋ 나랑 단둘이 있는 게 그렇게 좋냐구~! 진짜 모루궤어여 편하게 해라 주르르디안"},
                {"role": "user", "content": "나 감기 걸렸나 봐 머리가 너무 아프네..."},
                {"role": "assistant", "content": "평소에 조심하라고 내가 몇 번을 말했냐 바보냐구~! 마음 쓰이게 아프고 그래 진짜... 얼른 약 먹고 이불 속으로 기어 들어가서 자라 알겠지?"}
            ]

            # 유저가 보낸 진짜 텍스트 추가
            user_real_input = {"role": "user", "content": message.content}
            base_messages.append(user_real_input)

            # 구글 Gemini 호출
            chat_completion = ai_client.chat.completions.create(
                model="gemini-2.5-flash",
                temperature=0.85,
                messages=base_messages
            )

            reply = chat_completion.choices[0].message.content

            if reply and reply.strip():
                await message.channel.send(reply)
            else:
                print("❌ 구글 서버 응답 비어있음")
                await message.channel.send("어라... 나 방금 멍 때렸어 ㅋㅋㅋ 다시 말해봐!")

        except Exception as e:
            print(f"❌ 에러 발생 로그: {e}")
            await message.channel.send("으앙, 서버가 또 아픈가 봐구만.. 조금 이따가 다시 말 걸어줘!")


# 🚫 검열되었을 때 메시지를 삭제하고 쿠사리를 날리는 공통 함수
async def handle_censorship(message):
    try:
        # 유저가 쓴 문제의 메시지 삭제
        await message.delete()
        
        # 주르르 컨셉의 매운맛 쿠사리 전송
        await message.channel.send(
            f"⚠️ {message.author.mention} 방금 입에서 튀어나온 말 뭐냐구~! "
            f"어디서 못된 것만 배워와서 헛소리야 진짜 ㅋㅋㅋ 한 번만 더 선 넘으면 아주 그냥 차단 박아버릴 테니까 이쁜 말만 해라!"
        )
    except discord.Forbidden:
        print("❌ 에러: 봇에게 '메시지 관리' 권한이 없습니다.")
    except discord.HTTPException as e:
        print(f"❌ 메시지 삭제 실패: {e}")

# 봇 실행
client.run(DISCORD_TOKEN)
