"""Output capabilities come from catalog metadata, never input modalities."""


def agent_output(name: str) -> str:
    return {
        "audio-generation": "audio",
        "voice-cloning": "audio",
        "modify-image": "image",
        "image-generation": "image",
        "resize-image": "image",
        "video-generation": "video",
    }.get(name, "text")


def output_modalities(metadata: dict | None) -> list[str]:
    metadata = metadata or {}
    catalog = metadata.get("catalog") or {}
    architecture = catalog.get("architecture") or {}
    outputs = architecture.get("output_modalities")
    if outputs is None:
        # Older catalog snapshots encode input->output in a single string.
        modality = architecture.get("modality", "")
        outputs = modality.split("->", 1)[1].split("+") if "->" in modality else []
    result = set(outputs) if isinstance(outputs, list) else set()
    if "speech" in result:
        result.remove("speech")
        result.add("audio")
    for kind in ("image", "video"):
        if metadata.get(kind):
            result.add(kind)
    return sorted(result)


def model_catalog(rows) -> list[dict]:
    """Group legacy duplicate records while retaining IDs used by agent settings."""
    models = {}
    for row in rows:
        key = row.openrouter_id.strip()
        item = models.setdefault(key, dict(id=row.id, name=row.name, openrouter_id=key,
                                          model_ids=[], output_modalities=[]))
        item["model_ids"].append(row.id)
        item["output_modalities"] = sorted(set(item["output_modalities"]) |
                                           set(output_modalities(row.metadata_)))
    return list(models.values())
