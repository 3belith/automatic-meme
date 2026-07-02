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

        # 1. AI 응답을 받는 동안만 "말 쓰는 중..." 표시가 뜨도록 제한
        async with message.channel.typing():
            chat_completion = await ai_client.chat.completions.create(
                model="Llama-3.3-70b-Instruct",
                temperature=0.85,
                messages=messages
            )
            reply = chat_completion.choices[0].message.content.strip()

        # [수정] 이 시점에서 타이핑(말 쓰는 중...) 표시가 디스코드 창에서 꺼집니다.

        if reply == "CENSOR":
            await handle_censorship(message)
            return

        if reply:
            # 원본 응답 저장용
            full_reply = reply
            
            # 2. 줄바꿈 기준 쪼개되, 너무 잘게 쪼개져서 도배되지 않도록 뭉치는 로직
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

            # 아무리 많이 쪼개져도 최대 3개 메시지까지만 연속 전송하도록 제한 (과도한 뇌절 방지)
            final_messages = final_messages[:3]

            # 3. 정돈된 메시지를 약간의 간격을 두고 전송
            for idx, msg_content in enumerate(final_messages):
                await message.channel.send(msg_content)
                if idx < len(final_messages) - 1:
                    # 다음 답장까지 0.7초 대기 (실제 카톡/디코 템포)
                    await asyncio.sleep(0.7)
            
            # 메모리에는 전체 답변 통째로 저장해야 맥락을 안 잃어버림
            history.append({"role": "user", "content": message.content})
            history.append({"role": "assistant", "content": full_reply})
            
            if len(history) > MAX_MEMORY * 2:
                user_conversations[user_id] = history[-MAX_MEMORY * 2:]
        else:
            await message.channel.send("어라라? 방금 디코 억까 당함 ㅋㅋㅋ 렉 걸려서 메시지 날아갔잔슴;; 다시 보내봐!")

    except Exception as e:
        print(f"에러 로그: {e}")
        await message.channel.send("아잇, 지금 잠시 렉 걸렸잔슴! 좀 있다 다시 한번만 말 걸어줘!")
