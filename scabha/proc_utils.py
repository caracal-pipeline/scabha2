# -*- coding: future_fstrings -*-
import subprocess
import shlex
import glob
import os, os.path, stat
import shutil

def which(binary, extra_paths=None):
    """Equivalent of shell which command. Returns full path to executable, or None if not found"""
    for path in (extra_paths or []) + os.environ['PATH'].split(os.pathsep):
        fullpath = os.path.join(path, binary)
        if os.path.isfile(fullpath) and os.stat(fullpath).st_mode & stat.S_IXUSR:
            return fullpath
    return None

