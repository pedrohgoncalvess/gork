from api.routes.webhook.evolution.handles.core import COMMANDS, clean_text, has_explicit_command, is_message_too_old
from api.routes.webhook.evolution.handles.utility import handle_help_command, handle_model_command, handle_resume_command, handle_consumption_command
from api.routes.webhook.evolution.handles.audio import handle_transcribe_command, transcribe_audio
from api.routes.webhook.evolution.handles.search import handle_search_command
from api.routes.webhook.evolution.handles.image import handle_image_command, handle_describe_image_command, handle_sticker_command, handle_list_images_command, handle_picture_command
from api.routes.webhook.evolution.handles.reminder import handle_remember_command
from api.routes.webhook.evolution.handles.social import handle_twitter_command, handle_instagram_command
from api.routes.webhook.evolution.handles.chat import handle_conversation_agent
from api.routes.webhook.evolution.handles.favorite import handle_favorite_message, handle_list_favorites_message, handle_remove_favorite
