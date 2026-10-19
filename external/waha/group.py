from external.waha.base import chat_id, request, segment, waha_session


async def get_group_info(group_id: str) -> dict:
    group_id = group_id if group_id.endswith("@g.us") else group_id + "@g.us"
    result = await request("GET", f"/api/{segment(waha_session)}/groups/{segment(chat_id(group_id))}")
    return {
        **result, "subject": (result.get("subject") or result.get("Name") or result.get("name")
                               or (result.get("GroupName") or {}).get("Name")),
        "desc": (result.get("desc") or result.get("Topic") or result.get("description")
                 or (result.get("GroupTopic") or {}).get("Topic")),
    }
