from datetime import datetime

import httpx

from database import PgConnection
from database.models.base import Group, User
from database.models.content import Message
from database.operations.base.group import GroupRepository
from database.operations.base.user import UserRepository
from database.operations.content.message import MessageRepository
from external import get_url_content
from services import manage_interaction
from external.evolution import send_message
from utils import get_env_var


async def web_search(user_question: str, user_id: int, contact_id: str, is_group: bool = True):
    brave_key = get_env_var("BRAVE_KEY")

    headers = {
        "Content-Type": "application/json",
        "x-subscription-token": brave_key
    }

    async with PgConnection() as db:
        user_repo = UserRepository(User, db)
        message_repo = MessageRepository(Message, db)
        group_repo = GroupRepository(Group, db)

        if is_group:
            group = await group_repo.find_by_src_id(contact_id.replace("@g.us", ""))
            messages = await message_repo.find_by_group(group.id, 15)
        else:
            user = await user_repo.find_by_lid(contact_id.replace("@lid", ""))
            messages = await message_repo.find_by_sender(user.id, 15)

        formatted_messages = []

        exist_last_message = False
        for msg in messages:
            sender_name = msg.sender.name or msg.sender.phone_jid or "Usuário Desconhecido"
            content = msg.content or ""

            if content.strip() == user_question.strip():
                exist_last_message = True

            msg_date = msg.created_at.date()
            today = datetime.now().date()

            if msg_date != today:
                timestamp = msg.created_at.strftime('%d/%m/%Y %H:%M')
            else:
                timestamp = msg.created_at.strftime('%H:%M')

            formatted_messages.append(f"{sender_name}: {content} - {timestamp}")

        if not exist_last_message:
            formatted_messages.append(f"Ultima mensagem enviada: {user_question} - {datetime.now().strftime('%H:%M')}")

        final_message = "\n".join(formatted_messages)

        term_search = await manage_interaction(db, final_message, agent_name="term-search", user_id=user_id, group_id=group.id if is_group else None)
        message_term_formatted = await manage_interaction(db, term_search, agent_name="term-formatter", user_id=user_id, group_id=group.id if is_group else None)

        await send_message(contact_id, message_term_formatted)
        async with httpx.AsyncClient() as client:
            params = {"q": term_search}
            response = await client.get("https://api.search.brave.com/res/v1/web/search", params=params, headers=headers)
            body = response.json()
            videos_data = body.get("videos", {"results": []})
            video_reference = videos_data["results"][0] if len(videos_data["results"]) > 0 else None
            web_data = body.get("web", {"results": []})
            web_data_length = 8 if len(web_data["results"]) > 8 else len(web_data["results"])

            web_references = web_data["results"][:web_data_length] if web_data["results"] else []

            if not web_references:
                return f"Não consegui encontrar nada na internet com o tema {term_search}"

            tt_web_references = []
            for idx, web_reference in enumerate(web_references):
                tt_web_references.append(f"""
                    {idx} - {web_reference["title"]}
                    URL - {web_reference["url"]}
                    Description - {web_reference.get("description")}
                    Date of publication - {web_reference.get("page_age")}
                    Subtype - {web_reference.get("subtype")}
                    Age - {web_reference.get("age")}
                """.strip())


            final_message_sources = "\n\n".join(tt_web_references)
            final_message_source_selector = f"""
            Users interactions:
            {final_message}
            
            Sources:
            {final_message_sources}
            """

            web_sources = await manage_interaction(db, final_message_source_selector, agent_name="source-selector", user_id=user_id, group_id=group.id if is_group else None)
            tt_web_sources = [int(idx.strip()) for idx in web_sources.split(",")]

            tt_final_sources = []
            for idx in tt_web_sources:
                source = web_references[idx]
                url = source["url"]
                content = get_url_content(url)
                if not content:
                    not_selected_web_sources = [idx for idx, _  in enumerate(web_references) if idx not in tt_web_sources]
                    tt_web_sources.append(not_selected_web_sources[0])
                    continue

                tt_final_sources.append(f"""
                    Title: {source["title"]}
                    URL: {source["url"]}
                    Description: {source.get("description")}
                    Subtype: {source.get("subtype")}
                    Content: {content}
                    Age: {source.get("age")}
                """)

            message_tt_sources = "\n\n".join(tt_final_sources)

            if video_reference:
                video_mention = f"""
                Title: {video_reference["title"]}
                URL: {video_reference["url"]}
                Description: {video_reference.get("description")}
                Age: {video_reference.get("age")}
                Duration: {video_reference.get("video", {}).get("duration")}
                Creator: {video_reference.get("video", {}).get("creator")}
                """
            else:
                video_mention = None

            final_message_tt_sources = f"""
            Text sources: {message_tt_sources}
            """

            final_message_tt_sources = final_message_tt_sources if video_mention else final_message_sources + f"\n\nVideo source: {video_mention}"

            resume = await manage_interaction(db, final_message_tt_sources, agent_name="source-resumer", user_id=user_id, group_id=group.id if is_group else None)

            return resume