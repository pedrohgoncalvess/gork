"""Inventory of encrypted fields and their cryptographic domains."""
# IDs which can contain a telephone number must be encrypted as well.
TEXT_FIELDS = {
    'base.user': {'src_id': ('identity', True), 'phone_number': ('identity', True),
                  'name': ('user.name', True)},
    'base.group': {'name': ('group.name', True), 'description': ('group.description', False),
                   'profile_image_url': ('group.profile_image_url', False)},
    'content.message': {'content': ('message.content', False)},
    'content.media': {'name': ('media.name', False), 'description': ('media.description', False)},
    'manager.remember': {'message': ('remember.message', False)},
    'manager.observation': {'content': ('observation.content', True)},
    'manager.embedding': {'term': ('embedding.term', True)},
    'manager.disabled_command': {'message': ('disabled_command.message', False)},
    'ai.interaction': {key: ('interaction.' + key, False) for key in ('user_prompt', 'response', 'system_behavior')},
    'ai.agent': {'prompt': ('agent.prompt', False)},
    'ai.mcp_server': {key: ('mcp_server.' + key, False) for key in ('name', 'description', 'url', 'last_error')},
    'base.app_settings': {key: ('identity', True) for key in ('phone_number', 'lid', 'test_number')},
    'base.sync_job': {'error': ('sync.error', False)},
    'content.waha_message_reference': {'provider_id': ('reference.provider_id', False), 'chat_id': ('identity', True)},
    'manager.group_ban_poll': {'target_name': ('ban.target_name', False), 'target_id': ('identity', True)},
    'manager.group_ban_vote': {'voter_id': ('identity', True)},
}

JSON_FIELDS = {
    'content.waha_message_reference': {'media': 'reference.media'},
    'ai.mcp_server': {'tools': 'mcp_server.tools'},
}
