"""Redact fixed MCP credentials even in SDK transport exception logs."""
from contextvars import ContextVar
import logging
import traceback
from urllib.parse import quote, quote_plus


secrets_in_context = ContextVar("mcp_connection_secrets", default=())


class McpLogFilter(logging.Filter):
    def filter(self, record):
        values = secrets_in_context.get()
        if not values:
            return True
        message = record.getMessage()
        if record.exc_info:
            message += "\n" + "".join(traceback.format_exception(*record.exc_info))
            record.exc_info, record.exc_text = None, None
        for value in values:
            for encoded in {value, quote(value, safe=""), quote_plus(value)}:
                message = message.replace(encoded, "[REDACTED]")
        record.msg, record.args = message, ()
        return True


log_filter = McpLogFilter()


def protect_logs(settings):
    values = [str(value) for value in settings.get("headers", {}).values()]
    values += [str(value) for value in settings.get("params", {}).values()]
    authorization = next((value for key, value in settings.get("headers", {}).items() if key.lower() == "authorization"), "")
    if " " in authorization:
        values.append(authorization.split(" ", 1)[1])
    for name in list(logging.Logger.manager.loggerDict):
        if name.startswith(("mcp.", "httpx2")):
            logger = logging.getLogger(name)
            if log_filter not in logger.filters:
                logger.addFilter(log_filter)
    return secrets_in_context.set(tuple(sorted({value for value in values if len(value) >= 4}, key=len, reverse=True)))
