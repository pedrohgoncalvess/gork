from datetime import datetime

from database.models.manager import Model, Agent, Interaction
from database.operations.manager import ModelRepository, AgentRepository, InteractionRepository
from external import make_request_openrouter


async def manage_interaction(
        db,
        user_prompt: str,
        system_prompt: str = None,
        agent_name: str = None,
) -> str:

    model_repo = ModelRepository(Model, db)
    agent_repo = AgentRepository(Agent, db)

    default_model = await model_repo.get_default_model()
    agent = await agent_repo.find_by_name(agent_name) if agent_name else None

    if system_prompt is not None and agent_name is not None:
        system_prompt = f"{agent.prompt}\n\n{system_prompt}"

    if system_prompt is None and agent_name is not None:
        system_prompt = agent.prompt

    now = datetime.now()

    system_prompt = system_prompt.replace("{CURRENT_DATE}", now.strftime("%B %d, %Y"))
    system_prompt = system_prompt.replace("{CURRENT_YEAR}", str(now.year))
    system_prompt = system_prompt.replace("{CURRENT_MONTH_YEAR}", now.strftime("%B %Y"))

    payload_term_formatter = {
        "model": default_model.openrouter_id,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            }
        ]
    }

    llm_req = make_request_openrouter(payload_term_formatter)
    llm_resp = llm_req["choices"][0]["message"]["content"]

    interaction_repo = InteractionRepository(Interaction, db)
    first_interaction_term_formatter = await interaction_repo.create_interaction(
        agent_id=agent.id if agent_name else None,
        model_id=default_model.id,
        sender="user",
        content=f"System: {agent.prompt}\n\nUser: {llm_resp}",
        tokens=llm_req["usage"]["prompt_tokens"]
    )

    _ = await interaction_repo.create_interaction(
        agent_id=agent.id if agent_name else None,
        interaction_id=first_interaction_term_formatter.id,
        model_id=default_model.id,
        sender="assistant",
        content=llm_resp,
        tokens=llm_req["usage"]["completion_tokens"]
    )

    return llm_resp