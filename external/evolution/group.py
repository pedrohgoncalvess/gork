import httpx

from external.evolution.base import evolution_api, evolution_api_key, evolution_instance_name


def get_group_info(group_id: str) -> dict:
    headers = {
        "Content-Type": "application/json",
        "apikey": evolution_api_key,
    }

    req = httpx.get(f"{evolution_api}/group/findGroupInfos/{evolution_instance_name}?groupJid={group_id}", headers=headers)
    return req.json()
