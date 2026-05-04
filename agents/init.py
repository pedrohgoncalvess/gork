import asyncio

import yaml
from pathlib import Path

from database import PgConnection
from database.models.manager import Agent
from database.operations.manager import AgentRepository, ModelRepository
from log import logger
from utils import project_root


async def init_agents() -> None:
    agents_dir = Path(project_root) / "agents"
    yaml_path = agents_dir / "agents.yaml"

    if not yaml_path.exists():
        await logger.error("Agents", "Initialization", "agents.yaml not found.")
        return

    with open(yaml_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not config or "agents" not in config:
        await logger.error("Agents", "Initialization", "No agents found in agents.yaml.")
        return

    async with PgConnection() as db:
        agent_repo = AgentRepository(db)
        model_repo = ModelRepository(db)

        all_models = await model_repo.find_all()
        models_rel = {m.openrouter_id:m.id for m in all_models}

        for agent_data in config["agents"]:
            name = agent_data["name"]
            model_id = agent_data["model"]
            prompt_path_str = agent_data["prompt_path"]

            prompt_path = Path(project_root) / prompt_path_str
            if prompt_path.exists():
                with open(prompt_path, "r", encoding="utf-8") as f:
                    prompt_content = f.read()
            else:
                prompt_content = ""
                await logger.error("Agents", "Initialization", f"Prompt file not found for agent: {name}")

            model_db_id = models_rel.get(model_id)

            if not model_db_id:
                await logger.error("Agents", "Initialization", f"Model {model_id} not found.")

            await agent_repo.upsert_by_name(
                name=name,
                prompt=prompt_content,
                model_id=model_db_id
            )

    await logger.info("Agents", "Initialization", "Successful")


if __name__ == "__main__":
    asyncio.run(
        init_agents()
    )