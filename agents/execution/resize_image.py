import base64
from typing import Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content import Message
from database.operations.manager import AgentRepository, ModelConversationRepository
from external.openrouter import generate_images
from log import logger


class ResizeImageError(RuntimeError):
    """Raised when the AI resize request cannot produce a usable image."""


async def resize_image_agent(
    db: AsyncSession,
    user_id: int,
    db_message: Message,
    image_base64: str,
    sizes: Tuple[int, int]
) -> str:
    agent_repo = AgentRepository(db)
    model_conversation_repo = ModelConversationRepository(db)

    agent = await agent_repo.find_by_name('resize-image')
    if not agent:
        message = 'Resize image agent not found in database. Did init_agents run?'
        await logger.error('Agent', 'ResizeImage', message)
        raise ResizeImageError(message)

    model = await model_conversation_repo.resolve_agent_model(
        agent,
        user_id=user_id,
        group_id=db_message.group_id,
    )
    if not model:
        message = f'Model not found for agent {agent.name} (model_id={agent.model_id}).'
        await logger.error('Agent', 'ResizeImage', message)
        raise ResizeImageError(message)

    width, height = sizes
    prompt = f'Resize this image to {width}x{height}.'
    if agent.prompt:
        prompt = agent.prompt + ' ' + prompt

    await logger.info('Agent', 'ResizeImage', f'Calling model={model.openrouter_id} for resize to {width}x{height}')

    payload = {
        'model': model.openrouter_id,
        'prompt': prompt,
        'aspect_ratio': '1:1',
        'output_format': 'png',
        'input_references': [
            {
                'type': 'image_url',
                'image_url': {
                    'url': f'data:image/png;base64,{image_base64}'
                }
            }
        ]
    }

    try:
        resp = await generate_images(payload)
    except Exception as e:
        await logger.error('Agent', 'ResizeImage', f'generate_images call failed: {type(e).__name__}: {e}')
        raise ResizeImageError('OpenRouter failed to resize the image.') from e

    # Format 1: data array (e.g. DALL-E style)
    data = resp.get('data')
    if data and isinstance(data, list) and len(data) > 0:
        first = data[0]
        if isinstance(first, dict):
            if first.get('b64_json'):
                await logger.info('Agent', 'ResizeImage', 'Got b64_json from data array')
                return first['b64_json']
            if first.get('url'):
                await logger.info('Agent', 'ResizeImage', f'Got URL from data array, downloading...')
                try:
                    import httpx
                    async with httpx.AsyncClient(timeout=60) as client:
                        img_resp = await client.get(first['url'])
                        img_resp.raise_for_status()
                        return base64.b64encode(img_resp.content).decode('utf-8')
                except Exception as e:
                    await logger.error('Agent', 'ResizeImage', f'Failed to download image from URL: {e}')
                    raise ResizeImageError('Failed to download the resized image.') from e

    # Format 2: choices array (chat-completion style with images)
    choices = resp.get('choices')
    if choices and isinstance(choices, list) and len(choices) > 0:
        message = choices[0].get('message') if isinstance(choices[0], dict) else None
        images = message.get('images') if isinstance(message, dict) else None
        if images and isinstance(images, list) and len(images) > 0:
            img_data = images[0]
            if isinstance(img_data, dict):
                image_url = img_data.get('image_url')
                url = image_url.get('url') if isinstance(image_url, dict) else None
                if url:
                    if url.startswith('data:') and ',' in url:
                        await logger.info('Agent', 'ResizeImage', 'Got data URL from choices')
                        return url.split(',', 1)[1]
                    await logger.info('Agent', 'ResizeImage', f'Got URL from choices, downloading...')
                    try:
                        import httpx
                        async with httpx.AsyncClient(timeout=60) as client:
                            img_resp = await client.get(url)
                            img_resp.raise_for_status()
                            return base64.b64encode(img_resp.content).decode('utf-8')
                    except Exception as e:
                        await logger.error('Agent', 'ResizeImage', f'Failed to download image from URL: {e}')
                        raise ResizeImageError('Failed to download the resized image.') from e

    message = f'Could not extract image from response. Keys: {list(resp.keys()) if isinstance(resp, dict) else type(resp).__name__}'
    await logger.error('Agent', 'ResizeImage', message)
    raise ResizeImageError(message)
