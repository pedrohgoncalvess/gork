from api.routes.webhook.evolution.functions import web_search
from external.evolution import send_message


async def handle_search_command(
        remote_id: str,
        message_id: str,
        treated_text: str,
        group: bool,
        user_id: int
):
    search = await web_search(treated_text, user_id, remote_id, group)
    await send_message(remote_id, search, message_id)
