""" Asynchronous Relational Logger Module

This module provides a structured logging system that writes logs in a relational format,
similar to database records with consistent delimiters.
The logs are stored in files organized by date, making them easy to parse and analyze.

Features:
- Asynchronous file operations using aiofiles
- Date-based log file partitioning
- Configurable log formats and separators
- Environment-aware logging
- Support for different log levels (INFO, ERROR)

Usage:
from log import logger

# Log information
await logger.info("ModuleName", "OperationType", "Detailed message")

# Log errors
await logger.error("ModuleName", "ErrorType", "Exception details")
"""
import functools
import re
import os
from datetime import datetime
from string import Template
from functools import reduce
from typing import Optional

import aiofiles

from utils.env_var import get_env_var
from utils.path_config import project_root


class StructuredLogger:
    def __init__(self, log_format: Optional[str] = None, file_name: Optional[str] = None):
        log_append_path = get_env_var("LOG_APPEND_PATH")
        log_path = get_env_var("LOG_PATH")

        self._log_append_path_ = log_append_path if log_append_path is not None else True
        default_log_dir = f"{project_root}/log/"

        if self._log_append_path_:
            self._log_file_dir_ = f"{project_root}/{log_path}" if log_path else default_log_dir
        else:
            self._log_file_dir_ = log_path if log_path else default_log_dir

        self._log_file_format_ = f".{re.sub(r'[^a-zA-Z0-9]', '', log_format)}.log" if log_format else ".log"
        self.partition_by = datetime.now().strftime("%Y_%m_%d")
        self._file_name_ = f"{file_name}-{self.partition_by}" if file_name else self.partition_by
        self._log_path_ = f"{self._log_file_dir_}/{self._file_name_}{self._log_file_format_}"
        self._env_ = get_env_var("ENV") if get_env_var("ENV") is not None else "dev"

        self.sep = "|"
        self.row_sep = "\n"
        self.headers = ["MODE", "CREATED_AT", "MODULE", "MESSAGE", "DETAIL"]
        self.time_format = "%Y-%m-%d %H:%M:%S"
        self.format = Template(self.sep.join(f" ${h.lower()} " for h in self.headers).strip())

    # TODO: Implement convertion to .parquet

    async def init(self):
        if not os.path.exists(self._log_file_dir_):
            os.makedirs(self._log_file_dir_)
        if not os.path.exists(self._log_path_):
            async with aiofiles.open(self._log_path_, "w") as f:
                await f.write(f" {self.sep} ".join(self.headers + [self.row_sep]))
        return self

    @staticmethod
    def debug(func):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            if self._env_.lower() == "dev":
                string_f = reduce(lambda acc, x: f"{acc} {x}", args, "")
                colors_set = {"error": ("\033[91m", "\033[0m"), "warn": ("\033[93m", "\033[0m"),}
                colors = colors_set.get(func.__name__)

                message = f"[LOGGER DEBUG]: {func.__name__.upper()} {self.sep} {string_f[0:80]} {self.sep} {datetime.now().strftime(self.time_format)}"
                final_message = f"""{colors[0]}{message}{colors[1]}""" if colors else message

                print(final_message)
            return await func(self, *args, **kwargs)
        return wrapper

    async def _write_log_(self, log_message: str):
        await self.init()
        async with aiofiles.open(self._log_path_, "a", encoding="utf-8") as f:
            await f.write(f"{log_message} {self.row_sep}")

    @debug
    async def error(self, module:str, error_type:str, exception: str | None = None):
        await self._write_log_(
            self.format.substitute(
                mode="ERROR",
                message=error_type,
                created_at=datetime.now().strftime(self.time_format),
                detail=str(exception).replace("\n", "") if exception else None,
                module=module
            )
        )

    @debug
    async def warn(self, module:str, error_type:str, exception: str | None = None):
        await self._write_log_(
            self.format.substitute(
                mode="WARN",
                message=error_type,
                created_at=datetime.now().strftime(self.time_format),
                detail=str(exception).replace("\n", "") if exception else None,
                module=module
            )
        )

    @debug
    async def info(self, module:str, info_type:str, message:str):
        await self._write_log_(
            self.format.substitute(
                mode="INFO",
                message=info_type,
                created_at=datetime.now().strftime(self.time_format),
                detail=message,
                module=module
            )
        )

# Customize your log formats and files
logger = StructuredLogger()
openrouter_logger = StructuredLogger(file_name="openrouter")