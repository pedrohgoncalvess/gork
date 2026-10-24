from agents._shared.conversation import conversation_agent as run_conversation


async def conversation_agent(db, user_id, last_message_id, group_id=None, additional_context=""):
    return await run_conversation(
        db, user_id, last_message_id, group_id, additional_context,
        agent_name="conversation-dm",
    )
