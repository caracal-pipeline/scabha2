# -*- coding: future_fstrings -*-
import subprocess
import shlex
import glob
import os, os.path, stat
import shutil

#from . import log, OUTPUT, MSDIR, 
#config, parameters_dict, parameters_prefix

def which(binary, extra_paths=None):
    """Equivalent of shell which command. Returns full path to executable, or None if not found"""
    for path in (extra_paths or []) + os.environ['PATH'].split(os.pathsep):
        fullpath = os.path.join(path, binary)
        if os.path.isfile(fullpath) and os.stat(fullpath).st_mode & stat.S_IXUSR:
            return fullpath
    return None

def convert_command(command):
    """Converts list or str command into a string and a list"""
    if type(command) is str:
        command_list = shlex.split(command)
    elif type(command) is list:
        command_list = command
        command = ' '.join(command)
    else:
        raise TypeError("command: list or string expected")
    return command, command_list


def prun(command):
    """
    Runs a single command given by a string, or a list (strings will be split into lists by whitespace).
    Calls clear_junk() afterwards.

    Returns 0 on success, or a subprocess.CalledProcessError instance on failure.
    """
    command, command_list = convert_command(command)

    log.info(f"Running {command}")
    try:
        subprocess.check_call(command_list)
    except subprocess.CalledProcessError as exc:
        log.error(f"{command_list[0]} exited with code {exc.returncode}")
        clear_junk()
        return exc
    clear_junk()
    return 0


def prun_multi(commands):
    """
    Runs multiple commands given by list.
    Calls clear_junk() afterwards.

    Returns list of ("command_string", exception) tuples, one for every command that failed.
    Empty list means all commands succeeded.
    """

    errors = []
    for command in commands:
        command, command_list = convert_command(command)
        log.info(f"Running {command}")
        try:
            subprocess.check_call(command_list)
        except subprocess.CalledProcessError as exc:
            log.error(f"{command_list[0]} exited with code {exc.returncode}")
            errors.append((command, exc))
    clear_junk()
    return errors


def clear_junk():
    """
    Clears junk output products according to cab "junk" config variable
    """
    for item in config.get("junk", []):
        for dest in [OUTPUT, MSDIR]:  # these are the only writable volumes in the container
            items = glob.glob(f"{dest}/{item}")
            if items:
                log.debug(f"clearing junk: {' '.join(items)}")
                for f in items:
                    if os.path.islink(f) or os.path.isfile(f):
                        os.remove(f)
                    elif os.path.isdir(f):
                        shutil.rmtree(f)

def parse_parameters(pardict=None, positional=None, mandatory=None, repeat=True, repeat_dict=None):
    """
    Converts dict of parameters into a list of command-line arguments

    pardict:     dict of parameters. If None, pulled from default config.
    positional:  list of positional parameters, if any
    mandatory:   list of mandatory parameters.
    repeat:      How to treat iterable parameter values. If a string (e.g. ","), list values will be passed as one
                 command-line argument, joined by that separator. If True, list values will be passed as
                 multiple repeated command-line options. If None, list values are not allowed.
    repeat_dict: Like repeat, but defines this behaviour per parameter. If supplied, then "repeat" is used
                 as the default for parameters not in repeat_dict.

    Returns list of arguments.
    """
    pardict = pardict or parameters_dict
    if repeat_dict is None:
        repeat_dict = {}
    pos_args = []

    def repeat_argument(key, value):
        repeat_policy = repeat_dict.get(key, repeat)
        value = map(str, value)
        if repeat_policy is True:
            return list(value)
        elif type(repeat_policy) is str:
            return repeat_policy.join(value)
        elif repeat_policy is None:
            raise TypeError(f"repeated parameter '{key}' not permitted")
        else:
            raise TypeError(f"unknown repeat policy: '{repeat_policy}'")

    # check for mandatory arguments
    if type(mandatory) is str:  # be defensive in case a single string argument is given
        mandatory = [mandatory]
    missing = set(mandatory or []).difference(pardict.keys())
    if missing:
        raise RuntimeError(f"mandatory parameter(s) {' '.join(missing)} missing")

    # positional arguments get removed from dict, so make a copy
    if positional:
        if type(positional) is str: # be defensive in case a single string argument is given
            positional = [positional]
        pardict = pardict.copy()
        for key in positional:
            if key in pardict:
                value = pardict.pop(key)
                if value in [None, False]:
                    continue
                elif hasattr(value, '__iter__') and type(value) is not str:
                    value = repeat_argument(key, value)
                    if type(value) is list:
                        pos_args += value
                    else:
                        pos_args.append(value)
                else:
                    pos_args.append(str(value))
            else:
                raise NameError(f"positional parameter '{key}' not defined in config")

    args = []
    for key, value in pardict.items():
        # ignore None or False values, they are considered unset
        if value in [None, False]:
            continue
        prefix = parameters_prefix[key]
        option = f'{prefix}{key}'
        # True values map to a single option
        if value is True:
            args.append(option)
        # iterable values -- insert repeated
        elif hasattr(value, '__iter__') and type(value) is not str:
            value = repeat_argument(key, value)
            if type(value) is list:
                for val in value:
                    args += [option, val]
            else:
                args += [option, value]
        else:
            args += [option, str(value)]

    return args + pos_args
