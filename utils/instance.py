from utils.env_var import get_env_var


INSTANCE_NUMBER = get_env_var("WHATSAPP_INSTANCE_NUMBER") or get_env_var("EVOLUTION_INSTANCE_NUMBER")
