import asyncio
from io import BytesIO
from pathlib import Path

import yaml

from database import PgConnection
from database.operations.content.sup_media import SupMediaRepository
from log import logger
from s3 import S3Client
from utils import project_root

BUCKET = "whatsapp"

CONTENT_TYPES = {
    "audio": "audio/mpeg",
    "video": "video/mp4",
    "image": "image/png",
}


async def init_assets() -> None:
    metadata_path = Path(project_root) / "assets" / "metadata.yaml"

    if not metadata_path.exists():
        await logger.error("Assets", "Initialization", "metadata.yaml not found.")
        return

    with open(metadata_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not config:
        await logger.error("Assets", "Initialization", "metadata.yaml is empty.")
        return

    s3 = S3Client()
    await s3.connect()

    async with PgConnection() as db:
        sup_media_repo = SupMediaRepository(db)

        for media_type in ("audio", "video", "image"):
            items = config.get(media_type)
            if not items or not isinstance(items, list):
                continue

            for item in items:
                name = item.get("name")
                local_path = item.get("path")

                if not name or not local_path:
                    continue

                file_path = Path(project_root) / local_path

                if not file_path.exists():
                    await logger.error(
                        "Assets", "Initialization",
                        f"File not found: {file_path}"
                    )
                    continue

                s3_sub_path = f"sup_media/{media_type}/{file_path.name}"

                already_exists = await s3.object_exists(BUCKET, s3_sub_path)
                if not already_exists:
                    file_bytes = file_path.read_bytes()
                    content_type = CONTENT_TYPES.get(media_type, "application/octet-stream")

                    loop = asyncio.get_event_loop()
                    buffer = BytesIO(file_bytes)
                    buffer.seek(0)

                    await loop.run_in_executor(
                        None,
                        s3.client.put_object,
                        BUCKET,
                        s3_sub_path,
                        buffer,
                        len(file_bytes),
                        content_type,
                    )

                    await logger.info(
                        "Assets", "Initialization",
                        f"Uploaded {name} -> s3://{BUCKET}/{s3_sub_path}"
                    )

                await sup_media_repo.upsert_by_name(
                    name=name,
                    bucket=BUCKET,
                    path=s3_sub_path,
                    media_type=media_type,
                )

    await logger.info("Assets", "Initialization", "Successful")


if __name__ == "__main__":
    asyncio.run(init_assets())
