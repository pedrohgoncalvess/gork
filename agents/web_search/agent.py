import json
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.base import User
from database.models.manager import Interaction
from database.operations.manager import AgentRepository, InteractionRepository, ModelConversationRepository, ModelRepository
from external import completions

async def _run_web_search(
        db: AsyncSession,
        user: User,
        query: str,
        group_id: Optional[int],
) -> str:
    model_repo = ModelRepository(db)
    agent_repo = AgentRepository(db)
    model_conv_repo = ModelConversationRepository(db)
    web_agent = await agent_repo.find_by_name("web-search")

    model = None
    if web_agent:
        model = await model_conv_repo.resolve_agent_model(
            web_agent,
            user_id=user.id,
            group_id=group_id
        )

    if not model:
        model = await model_repo.get_default_model()

    if web_agent and web_agent.prompt:
        system_prompt = web_agent.prompt
    else:
        system_prompt = (
            "Use web search to answer the query with current, source-backed information. "
            "Return a concise summary in the query language. Include source names and URLs when available."
        )

    payload = {
        "model": model.openrouter_id,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": query,
            }
        ]
    }

    if web_agent and web_agent.response_format:
        try:
            payload["response_format"] = json.loads(web_agent.response_format)
        except Exception:
            pass

    req = await completions(payload, is_online=True)
    result = req["choices"][0]["message"]["content"]

    if web_agent and web_agent.response_format:
        try:
            parsed_json = json.loads(result)
            if isinstance(parsed_json, dict) and "summary" in parsed_json:
                result = parsed_json["summary"]
        except Exception:
            pass

    interaction_repo = InteractionRepository(Interaction, db)
    _ = await interaction_repo.create_interaction(
        model_id=model.id,
        user_id=user.id,
        group_id=group_id,
        user_prompt=query,
        response=result,
        input_tokens=req["usage"]["prompt_tokens"],
        output_tokens=req["usage"]["completion_tokens"],
        system_behavior=system_prompt
    )

    return result
