from api.routes.webhook.waha.handles.audio import handle_transcribe_command, transcribe_audio
from api.routes.webhook.waha.handles.image.deactivate import handle_deactivate_command
from api.routes.webhook.waha.handles.chat import handle_conversation_agent
from api.routes.webhook.waha.handles.core import (
    clean_text,
    COMMANDS,
    get_explicit_command_feature,
    has_explicit_command,
    is_message_too_old,
)
from api.routes.webhook.waha.handles.favorite import (
    handle_favorite_message,
    handle_list_favorites_message,
    handle_remove_favorite,
)
from api.routes.webhook.waha.handles.image import (
    handle_describe_image_command,
    handle_generate_sticker_command,
    handle_image_command,
    handle_list_images_command,
    handle_picture_command,
    handle_sticker_command,
)
from api.routes.webhook.waha.handles.philo import handle_philo_command
from api.routes.webhook.waha.handles.reminder import handle_remember_command
from agents.video_generation.agent import handle_video_command
from api.routes.webhook.waha.handles.social import handle_instagram_command, handle_twitter_command
from api.routes.webhook.waha.handles.utility import (
    handle_consumption_command,
    handle_help_command,
    handle_model_command,
    handle_resume_command,
)
