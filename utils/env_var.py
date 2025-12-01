"""
Environment Variable Handler.

This module provides utilities for loading and accessing environment variables
from a .env file. Uses python-dotenv for environment variable management.

Functions:
    get_env_var(var: str) -> str | None: Retrieves environment variables.
"""


from dotenv import load_dotenv
import os

load_dotenv() # TODO: Change .env file depending on the environment.


def get_env_var(var: str) -> str | None:
    """Function that centralizes the search for variables in the locally loaded .env file

    :returns: Value the variable as string and if it doesn't find it returns None.
    """
    return os.getenv(var)