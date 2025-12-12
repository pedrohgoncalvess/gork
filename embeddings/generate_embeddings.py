import io
from datetime import datetime

import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

from log import openrouter_logger


# model = CLIPModel.from_pretrained("laion/CLIP-ViT-bigG-14-laion2B-39B-b160k") #1024
# processor = CLIPProcessor.from_pretrained("laion/CLIP-ViT-bigG-14-laion2B-39B-b160k")
model = CLIPModel.from_pretrained("laion/CLIP-ViT-H-14-laion2B-s32B-b79K") #1024
processor = CLIPProcessor.from_pretrained("laion/CLIP-ViT-H-14-laion2B-s32B-b79K")
model.eval()

async def generate_text_embeddings(text: str) -> list[float]:
    start = datetime.now()
    inputs = processor(text=[text], return_tensors="pt", padding=True, truncation=True)
    with torch.no_grad():
        text_emb = model.get_text_features(**inputs)
    text_emb = text_emb / text_emb.norm(p=2, dim=-1, keepdim=True)
    duration = datetime.now() - start
    minutes = duration.total_seconds() / 60
    r = text_emb.squeeze().cpu().numpy().tolist()
    await openrouter_logger.info("Embedding", "Text generation", f"Text: {text} - Time took: {minutes:.2f}")
    return r

async def generate_image_embeddings(decoded_base64: bytes) -> list[float]:
    start = datetime.now()
    image = Image.open(io.BytesIO(decoded_base64)).convert("RGB")
    inputs = processor(images=image, return_tensors="pt")
    with torch.no_grad():
        img_emb = model.get_image_features(**inputs)
    img_emb = img_emb / img_emb.norm(p=2, dim=-1, keepdim=True)
    duration = datetime.now() - start
    minutes = duration.total_seconds() / 60
    r = img_emb.squeeze().cpu().numpy().tolist()
    await openrouter_logger.info("Embedding", "Image generation", f"Time took: {minutes:.2f}")
    return r