from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import insert, select

from database import PgConnection
from database.models.manager import Model, ModelPrice
from external.openrouter import get_image_models, get_models, get_video_models
from log import logger


PRICE_FIELDS = {
    "prompt": "prompt_price",
    "completion": "completion_price",
    "request": "request_price",
    "image": "image_price",
    "web_search": "web_search_price",
    "internal_reasoning": "internal_reasoning_price",
    "input_cache_read": "input_cache_read_price",
    "input_cache_write": "input_cache_write_price",
}
MODEL_PRICE_JOB_ID = "openrouter-model-prices"


def _decimal_price(value: object) -> Decimal | None:
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def model_price_values(model_id: int, pricing: dict) -> dict:
    values = {"model_id": model_id, "pricing": pricing}
    for openrouter_field, database_field in PRICE_FIELDS.items():
        values[database_field] = _decimal_price(pricing.get(openrouter_field))
    return values


async def refresh_model_prices() -> int:
    """Fetch one catalog snapshot and persist prices for configured models."""
    catalog = await get_models()
    try:
        video_catalog = await get_video_models()
    except Exception as error:
        video_catalog = None
        await logger.warn("ModelPricing", "VideoCatalogRefreshFailed", str(error))
    try:
        image_catalog = await get_image_models()
    except Exception as error:
        image_catalog = None
        await logger.warn("ModelPricing", "ImageCatalogRefreshFailed", str(error))
    catalog_by_id = {
        item.get("id"): item
        for item in catalog
        if isinstance(item, dict) and item.get("id")
    }
    video_by_id = {
        item.get("id"): item
        for item in (video_catalog or [])
        if isinstance(item, dict) and item.get("id")
    }
    image_by_id = {
        item.get("id"): item
        for item in (image_catalog or [])
        if isinstance(item, dict) and item.get("id")
    }

    async with PgConnection() as db:
        result = await db.execute(select(Model))
        models = list(result.scalars().all())
        known_model_ids = {model.openrouter_id for model in models}
        for video_model in video_by_id.values():
            openrouter_id = video_model["id"]
            if openrouter_id in known_model_ids:
                continue
            model = Model(
                name=video_model.get("name") or openrouter_id,
                openrouter_id=openrouter_id,
                metadata_={"video": video_model},
            )
            db.add(model)
            models.append(model)
            known_model_ids.add(openrouter_id)
        if video_by_id:
            await db.flush()
        rows = []
        missing = []

        for model in models:
            remote_model = catalog_by_id.get(model.openrouter_id)
            pricing = remote_model.get("pricing") if remote_model else None
            metadata = dict(model.metadata_ or {})
            if remote_model:
                metadata["catalog"] = {
                    key: value
                    for key, value in remote_model.items()
                    if key != "pricing"
                }
            video_model = video_by_id.get(model.openrouter_id)
            if video_model:
                metadata["video"] = video_model
                pricing = dict(pricing or {})
                pricing["video_skus"] = video_model.get("pricing_skus", {})
            image_model = image_by_id.get(model.openrouter_id)
            if image_model:
                metadata["image"] = image_model
            model.metadata_ = metadata
            if not isinstance(pricing, dict):
                missing.append(model.openrouter_id)
                continue
            rows.append(model_price_values(model.id, pricing))

        if rows:
            await db.execute(insert(ModelPrice), rows)
        await db.commit()

    if missing:
        await logger.warn(
            "ModelPricing",
            "ModelsWithoutPricing",
            ", ".join(missing),
        )
    await logger.info(
        "ModelPricing",
        "PricesRefreshed",
        f"Stored {len(rows)} pricing snapshots from {len(catalog)} catalog models.",
    )
    return len(rows)


async def refresh_model_prices_safely() -> None:
    try:
        await refresh_model_prices()
    except Exception as error:
        await logger.error("ModelPricing", "RefreshFailed", str(error))


def _schedule_next_refresh(scheduler: AsyncIOScheduler) -> None:
    scheduler.add_job(
        refresh_model_prices_and_reschedule,
        "date",
        run_date=datetime.now(timezone.utc) + timedelta(hours=2),
        args=[scheduler],
        id=MODEL_PRICE_JOB_ID,
        replace_existing=True,
    )


async def refresh_model_prices_and_reschedule(
    scheduler: AsyncIOScheduler,
) -> None:
    await refresh_model_prices_safely()
    _schedule_next_refresh(scheduler)


async def set_model_price_refresh(scheduler: AsyncIOScheduler) -> None:
    # Each request anchors a single next run, so downtime never creates catch-up
    # calls and a delayed execution always waits a full two hours afterward.
    await refresh_model_prices_safely()
    _schedule_next_refresh(scheduler)
