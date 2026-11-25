"""Apply the per-agent option to omit instructions from provider requests."""


def prompt_disabled(agent) -> bool:
    return getattr(agent, "disable_system_prompt", False) is True


def apply_prompt_setting(payload: dict, agent) -> None:
    if prompt_disabled(agent):
        payload["messages"] = [
            message for message in payload["messages"]
            if message["role"] not in {"system", "developer"}
        ]
