"""
Sets up essential path variables for the project using OS-independent path handling.

Variables: project_root (str): Absolute path of the project's root directory.
"""
import os

current_dir = os.path.dirname(os.path.abspath(__file__))

project_root = os.path.abspath(os.path.join(current_dir, "../"))