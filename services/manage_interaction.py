from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from database.models.manager import Model, Agent, Interaction, Command
from database.operations.manager import ModelRepository, AgentRepository, InteractionRepository
from external import completions


async def manage_interaction(
        db,
        user_prompt: str,
        user_id: int,
        group_id: Optional[int] = None,
        system_prompt: Optional[str] = None,
        agent_name: Optional[str] = None,
        command: Optional[Command] = None,
) -> str:

    model_repo = ModelRepository(Model, db)
    agent_repo = AgentRepository(Agent, db)

    default_model = await model_repo.get_default_model()
    agent = await agent_repo.find_by_name(agent_name) if agent_name else None

    if system_prompt is not None and agent_name is not None:
        system_prompt = f"{agent.prompt}\n\n{system_prompt}"

    if system_prompt is None and agent_name is not None:
        system_prompt = agent.prompt

    now = datetime.now(ZoneInfo("America/Sao_Paulo"))

    system_prompt = system_prompt.replace("{CURRENT_DATETIME}", now.strftime("%Y-%m-%d %H:%M:%S (%A)"))
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

    req = await completions(payload_term_formatter)
    resp = req["choices"][0]["message"]["content"]

    interaction_repo = InteractionRepository(Interaction, db)
    _ = await interaction_repo.create_interaction(
        model_id=default_model.id,
        user_id=user_id,
        group_id=group_id,
        agent_id=agent.id if agent_name else None,
        command_id=command.id if command else None,
        user_prompt=user_prompt,
        response=resp,
        input_tokens=req["usage"]["prompt_tokens"],
        output_tokens=req["usage"]["completion_tokens"],
        system_behavior=system_prompt
    )

    return resp