"""Select the conversation profile while keeping handlers transport-focused."""


async def conversation_agent(db, user_id, last_message_id, group_id=None, additional_context=""):
    if group_id:
        from agents.conversation_group.agent import conversation_agent as run
    else:
        from agents.conversation_dm.agent import conversation_agent as run
    return await run(db, user_id, last_message_id, group_id, additional_context)


async def parse_gork_response(output, group_id=None):
    if group_id:
        from agents.conversation_group.parser import parse_gork_response as parse
    else:
        from agents.conversation_dm.parser import parse_gork_response as parse
    return await parse(output)
