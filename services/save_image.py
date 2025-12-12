from datetime import datetime
from typing import Optional
from uuid import uuid4
import base64
import io

from database import PgConnection
from database.models.base import Group, User
from database.models.content import Media, Message
from database.operations.base import GroupRepository, UserRepository
from database.operations.content import MediaRepository, MessageRepository
from embeddings import generate_image_embeddings, generate_text_embeddings
from s3 import S3Client
from services import translate_to_pt

from PIL import Image
from transformers import Blip2Processor, Blip2ForConditionalGeneration



# from transformers import LlavaNextProcessor, LlavaNextForConditionalGeneration
# processor = LlavaNextProcessor.from_pretrained("llava-hf/llava-v1.6-mistral-7b-hf")
# model = LlavaNextForConditionalGeneration.from_pretrained("llava-hf/llava-v1.6-mistral-7b-hf")

processor = Blip2Processor.from_pretrained("Salesforce/blip2-opt-2.7b")
model = Blip2ForConditionalGeneration.from_pretrained("Salesforce/blip2-opt-2.7b")

def generate_title_image(base64_bytes: bytes) -> str:
    image = Image.open(io.BytesIO(base64.b64decode(base64_bytes)))

    inputs = processor(image, return_tensors="pt")
    output = model.generate(**inputs, max_new_tokens=20)

    caption = processor.decode(output[0], skip_special_tokens=True)
    return caption


async def materialize_image(message_id: str, image_base64: bytes, group_id: Optional[int] = None, user_id: Optional[int] = None) -> Media:
    s3_conn = S3Client()
    _ = await s3_conn.connect()
    async with PgConnection() as db:
        if group_id is not None:
            group_repo = GroupRepository(Group, db)
            group = await group_repo.find_by_id(group_id)
            ext_id = group.ext_id
        else:
            user_repo = UserRepository(User, db)
            user = await user_repo.find_by_id(user_id)
            ext_id = user.ext_id

        decoded = base64.b64decode(image_base64)
        name = generate_title_image(image_base64)
        translated_name = translate_to_pt(name)

        emb = await generate_image_embeddings(decoded)
        text_emb = await generate_text_embeddings(translated_name)

        image_id = uuid4()
        path = f"{ext_id}/{datetime.now().strftime("%Y-%m-%d")}/{image_id}.png"
        _ = await s3_conn.upload_image(
            decoded,
            object_name = path
        )

        media_repo = MediaRepository(Media, db)
        message_repo = MessageRepository(Message, db)
        message = await message_repo.find_by_message_id(message_id)
        new_media = await media_repo.insert(
            Media(
                ext_id=image_id, name=translated_name, message_id=message.id,
                bucket="whatsapp", path=path, format="png",
                size=len(decoded) / float((1024 * 1024)), image_embedding=emb,
                name_embedding=text_emb
            )
        )

        return new_media