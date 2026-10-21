async def get_instance_number():
    # Read shared storage so every worker observes connection/account changes.
    from services.setup import settings
    number = (await settings())["phone_number"]
    if not number:
        raise RuntimeError("Conecte o WhatsApp pelo painel para identificar a conta principal.")
    return number
