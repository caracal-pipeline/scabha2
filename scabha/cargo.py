import os.path, re, stat, itertools, logging, yaml, shlex, importlib
from typing import Any, List, Dict, Optional, Union
from enum import Enum
from dataclasses import dataclass
from omegaconf import MISSING


import scabha
from scabha import exceptions
from .exceptions import CabValidationError, ParameterValidationError, DefinitionError, SchemaError
from .validate import validate_parameters, Unresolved
from .substitutions import SubstitutionNS
from .basetypes import EmptyDictDefault, EmptyListDefault

## almost supported by omegaconf, see https://github.com/omry/omegaconf/issues/144, for now just use Any
ListOrString = Any   


Conditional = Optional[str]


@dataclass 
class ParameterPolicies(object):
    # if true, value is passed as a positional argument, not an option
    positional: Optional[bool] = None
    # if true, value is head-positional, i.e. passed *before* any options
    positional_head: Optional[bool] = None
    # for list-type values, use this as a separator to paste them together into one argument. Otherwise:
    #  * use "list" to pass list-type values as multiple arguments (--option X Y)
    #  * use "[]" to pass list-type values as a list  (--option [X,Y])
    #  * use "repeat" to repeat the option (--option X --option Y)
    repeat: Optional[str] = None
    # prefix for non-positional arguments
    prefix: Optional[str] = None

    # skip this parameter
    skip: bool = False
    # if True, implicit parameters will be skipped automatically
    skip_implicits: bool = True

    # how to pass boolean True values. None = pass option name alone, else pass option name + given value
    explicit_true: Optional[str] = None
    # how to pass boolean False values. None = skip option, else pass option name + given value
    explicit_false: Optional[str] = None

    # if set, a string-type value will be split into a list of arguments using this separator
    split: Optional[str] = None

    # dict of character replacements
    replace: Optional[Dict[str, str]] = None
    
    # Value formatting policies.
    # If set, specifies {}-type format strings used to convert the value(s) to string(s).
    # For a non-list value:
    #   * if 'format_list_scalar' is set, formats the value into a list of strings as fmt[i].format(value, **dict)
    #     example:  ["{0}", "{0}"] will simply repeat the value twice
    #   * if 'format' is set, value is formatted as format.format(value, **dict) 
    # For a list-type value:
    #   * if 'format_list' is set, each element #i formatted separately as fmt[i].format(*value, **dict)
    #     example:  ["{0}", "{2}"] will output elements 0 and 2, and skip element 1 
    #   * if 'format' is set, each element #i is formatted as format.format(value[i], **dict) 
    # **dict contains all parameters passed to a cab, so these can be used in the formatting
    format: Optional[str] = None
    format_list: Optional[List[str]] = None
    format_list_scalar: Optional[List[str]] = None



@dataclass 
class CabManagement:        # defines common cab management behaviours
    environment: Optional[Dict[str, str]] = EmptyDictDefault()
    cleanup: Optional[Dict[str, ListOrString]]     = EmptyDictDefault()   
    wranglers: Optional[Dict[str, ListOrString]]   = EmptyDictDefault()   


    

@dataclass
class Parameter(object):
    """Parameter (of cab or recipe)"""
    info: str = ""
    # for input parameters, this flag indicates a read-write (aka input-output aka mixed-mode) parameter e.g. an MS
    writable: bool = False
    # data type
    dtype: str = "str"
    # for file-type parameters, specifies that the filename is implicitly set inside the step (i.e. not a free parameter)
    implicit: Optional[str] = None
    # optonal list of arbitrary tags, used to group parameters
    tags: List[str] = EmptyListDefault()

    # if True, parameter is required
    required: bool = False

    # choices for an option-type parameter (should this be List[str]?)
    choices:  Optional[List[Any]] = ()

    # default value
    default: Optional[Any] = None

    # list of aliases for this parameter (i.e. references to other parameters whose schemas/values this parameter shares)
    aliases: Optional[List[str]] = ()

    # if true, treat parameter as a path, and ensure that the parent directories it refers to exist
    mkdir: bool = False
    
    # for file and dir-type parameters: if True, the file(s)/dir(s) must exist. If False, they can be missing.  
    # if None, then the default logic applies: inputs must exist, and outputs don't
    must_exist: Optional[bool] = None

    # if command-line option for underlying binary has a different name, specify it here
    nom_de_guerre: Optional[str] = None

    # policies object, specifying a non-default way to handle this parameter
    policies: ParameterPolicies = ParameterPolicies()

    # metavar corresponding to this parameter. Used when constructing command-line interfaces
    metavar: Optional[str] = None

    # abbreviated option name for this parameter.  Used when constructing command-line interfaces
    abbreviation: Optional[str] = None

    # inherited from Stimela 1 -- used to handle paremeters inside containers?
    # might need a re-think, but we can leave them in for now  
    pattern: Optional[str] = MISSING




@dataclass
class Cargo(object):
    name: Optional[str] = None                    # cab name (if None, use image or command name)
    fqname: Optional[str] = None                  # fully-qualified name (recipe_name.step_label.etc.etc.)

    info: Optional[str] = None                    # description
    inputs: Dict[str, Parameter] = EmptyDictDefault()
    outputs: Dict[str, Parameter] = EmptyDictDefault()
    defaults: Dict[str, Any] = EmptyDictDefault()

    backend: Optional[str] = None                 # backend, if not default

    dynamic_schema: Optional[str] = None          # function to call to augment inputs/outputs dynamically

    def __post_init__(self):
        self.fqname = self.fqname or self.name
        for name in self.inputs.keys():
            if name in self.outputs:
                raise DefinitionError(f"{name} appears in both inputs and outputs")
        self.params = {}
        self._inputs_outputs = None
        # pausterized name
        self.name_ = re.sub(r'\W', '_', self.name or "")  # pausterized name
        # config and logger objects
        self.config = self.log = self.logopts = None
        # resolve callable for dynamic schemas
        self._dyn_schema = None
        if self.dynamic_schema is not None:
            if '.' not in self.dynamic_schema:
                raise DefinitionError(f"{self.dynamic_schema}: module_name.function_name expected")
            modulename, funcname = self.dynamic_schema.rsplit(".", 1)
            try:
                mod = importlib.import_module(modulename)
            except ImportError as exc:
                raise DefinitionError(f"can't import {modulename}: {exc}")
            self._dyn_schema = getattr(mod, funcname, None)
            if not callable(self._dyn_schema):
                raise DefinitionError(f"{modulename}.{funcname} is not a valid callable")

    @property
    def inputs_outputs(self):
        if self._inputs_outputs is None:
            self._inputs_outputs = self.inputs.copy()
            self._inputs_outputs.update(**self.outputs)
        return self._inputs_outputs
    
    @property
    def invalid_params(self):
        return [name for name, value in self.params.items() if type(value) is exceptions.Error]

    @property
    def missing_params(self):
        return {name: schema for name, schema in self.inputs_outputs.items() if schema.required and name not in self.params}

    @property
    def unresolved_params(self):
        return [name for name, value in self.params.items() if type(value) is Unresolved]

    @property 
    def finalized(self):
        return self.config is not None

    def finalize(self, config=None, log=None, logopts=None, fqname=None, nesting=0):
        if not self.finalized:
            if fqname is not None:
                self.fqname = fqname
            self.config = config
            self.nesting = nesting
            self.log = log
            self.logopts = logopts

    def prevalidate(self, params: Optional[Dict[str, Any]], subst: Optional[SubstitutionNS]=None):
        """Does pre-validation. 
        No parameter substitution is done, but will check for missing params and such.
        A dynamic schema, if defined, is applied at this point."""
        self.finalize()
        # update schemas, if dynamic schema is enabled
        if self._dyn_schema:
            self._inputs_outputs = None
            self.inputs, self.outputs = self._dyn_schema(params, self.inputs, self.outputs)
        # prevalidate parameters
        self.params = validate_parameters(params, self.inputs_outputs, defaults=self.defaults, subst=subst, fqname=self.fqname,
                                          check_unknowns=True, check_required=False, check_exist=False,
                                          create_dirs=False, expand_globs=False, ignore_subst_errors=True)

        return self.params

    def _add_implicits(self, params: Dict[str, Any], schemas: Dict[str, Parameter]):
        # add implicit inputs
        for name, schema in schemas.items():
            if schema.implicit is not None:
                if name in params:
                    raise ParameterValidationError(f"implicit parameter {name} was supplied explicitly")
                if name in self.defaults:
                   raise SchemaError(f"implicit parameter {name} also has a default value")
                params[name] = schema.implicit

    def validate_inputs(self, params: Dict[str, Any], subst: Optional[SubstitutionNS]=None, loosely=False):
        """Validates inputs.  
        If loosely is True, then doesn't check for required parameters, and doesn't check for files to exist etc.
        This is used when skipping a step.
        """
        assert(self.finalized)
        # add implicit inputs
        params = params.copy()
        self._add_implicits(params, self.inputs)
        # check inputs
        params.update(**validate_parameters(params, self.inputs, defaults=self.defaults, subst=subst, fqname=self.fqname,
                                                check_unknowns=False, check_required=not loosely, check_exist=not loosely, 
                                                create_dirs=not loosely))
        # check outputs
        params.update(**validate_parameters(params, self.outputs, defaults=self.defaults, subst=subst, fqname=self.fqname, 
                                                check_unknowns=False, check_required=False, check_exist=False, 
                                                create_dirs=not loosely, expand_globs=False))
        self.params.update(**params)
        return self.params

    def validate_outputs(self, params: Dict[str, Any], subst: Optional[SubstitutionNS]=None, loosely=False):
        """Validates outputs. Parameter substitution is done. 
        If loosely is True, then doesn't check for required parameters, and doesn't check for files to exist etc.
        """
        assert(self.finalized)
        # add implicit outputs
        self._add_implicits(params, self.outputs)
        self.params.update(**validate_parameters(params, self.outputs, defaults=self.defaults, subst=subst, fqname=self.fqname,
                                                check_unknowns=False, check_required=not loosely, check_exist=not loosely))
        return self.params


    def update_parameter(self, name, value):
        assert(self.finalized)
        self.params[name] = value

    def make_substitition_namespace(self, ns=None):
        from .substitutions import SubstitutionNS
        ns = {} if ns is None else ns.copy()
        ns.update(**{name: str(value) for name, value in self.params.items()})
        ns.update(**{name: "MISSING" for name in self.missing_params})
        return SubstitutionNS(**ns)


ParameterPassingMechanism = Enum("scabha.ParameterPassingMechanism", "args yaml")


@dataclass 
class Cab(Cargo):
    """Represents a cab i.e. an atomic task in a recipe.
    See dataclass fields below for documentation of fields.

    Additional attributes available after validation with arguments:

        self.input_output:      combined parameter dict (self.input + self.output), maps name to Parameter
        self.missing_params:    dict (name to Parameter) of required parameters that have not been specified
    
    Raises:
        CabValidationError: [description]
    """
    # if set, the cab is run in a container, and this is the image name
    # if not set, commands are run by the native runner
    image: Optional[str] = None                   

    # command to run, inside the container or natively
    command: str = MISSING

    # if set, activates this virtual environment first before running the command (not much sense doing this inside the container)
    virtual_env: Optional[str] = None

    # controls how params are passed. args: via command line argument, yml: via a single yml string
    parameter_passing: ParameterPassingMechanism = ParameterPassingMechanism.args

    # cab management and cleanup definitions
    management: CabManagement = CabManagement()

    # default parameter conversion policies
    policies: ParameterPolicies = ParameterPolicies()

    # copy names of logging levels into wrangler actions
    wrangler_actions =  {attr: value for attr, value in logging.__dict__.items() if attr.upper() == attr and type(value) is int}

    # then add litetal constants for other wrangler actions
    ACTION_SUPPRESS = wrangler_actions["SUPPRESS"] = "SUPPRESS"
    ACTION_DECLARE_SUCCESS = wrangler_actions["DECLARE_SUCCESS"] = "DECLARE_SUPPRESS"
    ACTION_DECLARE_FAILURE = wrangler_actions["DECLARE_FAILURE"] = "DECLARE_FAILURE"


    def __post_init__ (self):
        if self.name is None:
            self.name = self.image or self.command.split()[0]
        Cargo.__post_init__(self)
        for param in self.inputs.keys():
            if param in self.outputs:
                raise CabValidationError(f"cab {self.name}: parameter {param} is both an input and an output, this is not permitted")
        # setup wranglers
        self._wranglers = []
        for match, actions in self.management.wranglers.items():
            replace = None
            if type(actions) is str:
                actions = [actions]
            if type(actions) is not list:
                raise CabValidationError(f"wrangler entry {match}: expected action or list of actions")
            for action in actions:
                if action.startswith("replace:"):
                    replace = action.split(":", 1)[1]
                elif action not in self.wrangler_actions:
                    raise CabValidationError(f"wrangler entry {match}: unknown action '{action}'")
            actions = [self.wrangler_actions[act] for act in actions if act in self.wrangler_actions]
            try:
                rexp = re.compile(match)
            except Exception as exc:
                raise CabValidationError(f"wrangler entry {match} is not a valid regular expression")
            self._wranglers.append((re.compile(match), replace, actions))
        self._runtime_status = None


    def summary(self, recursive=True):
        lines = [f"cab {self.name}:"] 
        for name, value in self.params.items():
            # if type(value) is validate.Error:
            #     lines.append(f"  {name} = ERR: {value}")
            # else:
            lines.append(f"  {name} = {value}")
                
        lines += [f"  {name} = ???" for name in self.missing_params.keys()]
        return lines


    def build_command_line(self, subst: Optional[Dict[str, Any]] = None):
        from .substitutions import substitutions_from

        with substitutions_from(subst, raise_errors=True) as context:
            venv = context.evaluate(self.virtual_env, location=["virtual_env"])
            command = context.evaluate(self.command, location=["command"])

        if venv:
            venv = os.path.expanduser(venv)
            if not os.path.isfile(f"{venv}/bin/activate"):
                raise CabValidationError(f"virtual environment {venv} doesn't exist", log=self.log)
            self.log.debug(f"virtual envirobment is {venv}")
        else:
            venv = None

        command_line = shlex.split(os.path.expanduser(command))
        command = command_line[0]
        args = command_line[1:]
        # collect command
        if "/" not in command:
            from scabha.proc_utils import which
            command0 = command
            command = which(command, extra_paths=venv and [f"{venv}/bin"])
            if command is None:
                raise CabValidationError(f"{command0}: not found", log=self.log)
        else:
            if not os.path.isfile(command) or not os.stat(command).st_mode & stat.S_IXUSR:
                raise CabValidationError(f"{command} doesn't exist or is not executable", log=self.log)

        self.log.debug(f"command is {command}")

        return ([command] + args + self.build_argument_list()), venv


    def build_argument_list(self):
        """
        Converts command, and current dict of parameters, into a list of command-line arguments.

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

        # collect parameters

        value_dict = dict(**self.params)

        if self.parameter_passing is ParameterPassingMechanism.yaml:
            return [yaml.dump(value_dict)]

        def get_policy(schema, policy):
            if schema.policies[policy] is not None:
                return schema.policies[policy]
            else:
                return self.policies[policy]

        def stringify_argument(name, value, schema, option=None):
            if value is None:
                return None
            if schema.dtype == "bool" and not value and get_policy(schema, 'explicit_false') is None:
                return None

            is_list = hasattr(value, '__iter__') and type(value) is not str
            format_policy = get_policy(schema, 'format')
            format_list_policy = get_policy(schema, 'format_list')
            format_scalar_policy = get_policy(schema, 'format_list_scalar')
            split_policy = get_policy(schema, 'split')
            
            if type(value) is str and split_policy:
                value = value.split(split_policy or None)
                is_list = True

            if is_list:
                # apply formatting policies to a list of values
                if format_list_policy:
                    if len(format_list_policy) != len(value):
                        raise CabValidationError("length of format_list_policy does not match length of '{name}'", log=self.log)
                    value = [fmt.format(*value, **value_dict) for fmt in format_list_policy]
                elif format_policy:
                    value = [format_policy.format(x, **value_dict) for x in value]
                else:
                    value = [str(x) for x in value]
            else:
                # apply formatting policies to a scalar valye
                if format_scalar_policy:
                    value = [fmt.format(value, **value_dict) for fmt in format_scalar_policy]
                    is_list = True
                elif format_policy:
                    value = format_policy.format(value, **value_dict)
                else:
                    value = str(value)

            if is_list:
                # check repeat policy and form up representation
                repeat_policy = get_policy(schema, 'repeat')
                if repeat_policy == "list":
                    return [option] + list(value) if option else list(value)
                elif repeat_policy == "[]":
                    val = "[" + ",".join(value) + "]"
                    return [option] + [val] if option else val
                elif repeat_policy == "repeat":
                    return list(itertools.chain([option, x] for x in value)) if option else list(value)
                elif type(repeat_policy) is str:
                    return [option, repeat_policy.join(value)] if option else repeat_policy.join(value)
                elif repeat_policy is None:
                    raise CabValidationError(f"list-type parameter '{name}' does not have a repeat policy set", log=self.log)
                else:
                    raise SchemaError(f"unknown repeat policy '{repeat_policy}'", log=self.log)
            else:
                return [option, value] if option else [value]

        # check for missing parameters and collect positionals

        pos_args = [], []

        for name, schema in self.inputs_outputs.items():
            if schema.required and name not in value_dict:
                raise CabValidationError(f"required parameter '{name}' is missing", log=self.log)
            if name in value_dict:
                positional_first = get_policy(schema, 'positional_head') 
                positional = get_policy(schema, 'positional') or positional_first
                skip = get_policy(schema, 'skip') or (schema.implicit and get_policy(schema, 'skip_implicits'))
                if positional:
                    if not skip:
                        pargs = pos_args[0 if positional_first else 1]
                        value = stringify_argument(name, value_dict[name], schema)
                        if type(value) is list:
                            pargs += value
                        elif value is not None:
                            pargs.append(value)
                    value_dict.pop(name)

        args = []
                    
        # now check for optional parameters that remain in the dict
        for name, value in value_dict.items():
            if name not in self.inputs_outputs:
                raise RuntimeError(f"unknown parameter '{name}'")
            schema = self.inputs_outputs[name]

            skip = get_policy(schema, 'skip') or (schema.implicit and get_policy(schema, 'skip_implicits'))
            if skip:
                continue

            # apply replacementss
            replacements = get_policy(schema, 'replace')
            if replacements:
                for rep_from, rep_to in replacements.items():
                    name = name.replace(rep_from, rep_to)

            option = (get_policy(schema, 'prefix') or "--") + (schema.nom_de_guerre or name)

            if schema.dtype == "bool":
                explicit = get_policy(schema, 'explicit_true' if value else 'explicit_false')
                args += [option, str(explicit)] if explicit is not None else ([option] if value else [])
            else:
                value = stringify_argument(name, value, schema, option=option)
                if type(value) is list:
                    args += value
                elif value is not None:
                    args.append(value)

        return pos_args[0] + args + pos_args[1]


    @property
    def runtime_status(self):
        return self._runtime_status

    def reset_runtime_status(self):
        self._runtime_status = None

    def apply_output_wranglers(self, output, severity):
        suppress = False
        modified_output = output
        for regex, replace, actions in self._wranglers:
            if regex.search(output):
                if replace is not None:
                    modified_output = regex.sub(replace, output)
                for action in actions:
                    if type(action) is int:
                        severity = action
                    elif action is self.ACTION_SUPPRESS:
                        suppress = True
                    elif action is self.ACTION_DECLARE_FAILURE and self._runtime_status is None:
                        self._runtime_status  = False
                        modified_output = "[FAILURE] " + modified_output
                        severity = logging.ERROR
                    elif action is self.ACTION_DECLARE_SUCCESS and self._runtime_status is None:
                        self._runtime_status = True
                        modified_output = "[SUCCESS] " + modified_output
        return (None, 0) if suppress else (modified_output, severity)





