import os.path, re, stat, itertools, logging, yaml, shlex, importlib
from typing import Any, List, Dict, Optional, Union
from collections import OrderedDict
from enum import Enum, IntEnum
from dataclasses import dataclass
from omegaconf import MISSING, ListConfig, DictConfig, OmegaConf

import rich.box
import rich.markup
from rich.table import Table
from rich.markdown import Markdown

import scabha
from scabha import exceptions
from .exceptions import CabValidationError, NestedSchemaError, ParameterValidationError, DefinitionError, SchemaError
from .validate import validate_parameters, Unresolved
from .substitutions import SubstitutionNS
from .basetypes import EmptyDictDefault, EmptyListDefault

## almost supported by omegaconf, see https://github.com/omry/omegaconf/issues/144, for now just use Any
ListOrString = Any   


Conditional = Optional[str]

@dataclass 
class ParameterPolicies(object):
    """This class describes policies that determine how a Parameter is turned into
    cab arguments. Most policies refer to how command-line arguments are formed up,
    although some also apply to Python callable cabs.
    """
    # if true, parameter is passed as key=value, not command line option
    key_value: Optional[bool] = None
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
    skip: Optional[bool] = None
    # if True, implicit parameters will be skipped automatically
    skip_implicits: Optional[bool] = None

    # if set, {}-substitutions on this paramater will not be done
    disable_substitutions: Optional[bool] = None

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

    # for Python callable cabs: if set, then missing parameters are passed as None values
    # if not set, missing parameters are not passed at all
    pass_missing_as_none: Optional[bool] = None



@dataclass 
class CabManagement:        # defines common cab management behaviours
    environment: Optional[Dict[str, str]] = EmptyDictDefault()
    cleanup: Optional[Dict[str, ListOrString]]     = EmptyDictDefault()   
    wranglers: Optional[Dict[str, ListOrString]]   = EmptyDictDefault()   


# used to classify parameters. Purely for cosmetic and help purposes
ParameterCategory = IntEnum("ParameterCategory", 
                            dict(Required=0, Optional=1, Implicit=2, Obscure=3, Hidden=4),
                            module=__name__)

@dataclass
class Parameter(object):
    """Parameter (of cab or recipe)"""
    info: str = ""
    # for input parameters, this flag indicates a read-write (aka input-output aka mixed-mode) parameter e.g. an MS
    writable: bool = False
    # data type
    dtype: str = "str"
    # specifies that the value is implicitly set inside the step (i.e. not a free parameter). Typically used with filenames 
    implicit: Any = None
    # optonal list of arbitrary tags, used to group parameters
    tags: List[str] = EmptyListDefault()

    # if True, parameter is required
    required: bool = False

    # restrict value choices, i.e. making for an option-type parameter 
    choices:  Optional[List[Any]] = ()

    # for List or Dict-type parameters, restict values of list elements or dict entries to a list of choices
    element_choices: Optional[List[Any]] = None

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

    # Parameter category, purely cosmetic, used for generating help and debug messages. 
    # Assigned automatically if None, but a schema may explicitly mark parameters as e.g. 
    # "obscure" or "hidden"
    category: Optional[ParameterCategory] = None

    # metavar corresponding to this parameter. Used when constructing command-line interfaces
    metavar: Optional[str] = None

    # abbreviated option name for this parameter.  Used when constructing command-line interfaces
    abbreviation: Optional[str] = None

    # arbitrary metadata associated with parameter
    metadata: Dict[str, Any] = EmptyDictDefault() 

    def __post_init__(self):
        def natify(value):
            # convert OmegaConf lists and dicts to native types
            if type(value) in (list, ListConfig):
                return [natify(x) for x in value]
            elif type(value) in (dict, OrderedDict, DictConfig):
                return OrderedDict([(name, natify(value)) for name, value in value.items()])
            return value
        self.default = natify(self.default)
        self.choices = natify(self.choices)

    def get_category(self):
        """Returns category of parameter, auto-setting it if not already preset"""
        if self.category is None:
            if self.required:
                self.category = ParameterCategory.Required
            elif self.implicit is not None:
                self.category = ParameterCategory.Implicit
            else:
                self.category = ParameterCategory.Optional
        return self.category

ParameterSchema = OmegaConf.structured(Parameter)

@dataclass
class Cargo(object):
    name: Optional[str] = None                    # cab name (if None, use image or command name)
    fqname: Optional[str] = None                  # fully-qualified name (recipe_name.step_label.etc.etc.)

    info: Optional[str] = None                    # description

    # schemas are postentially nested (dicts of dicts), which omegaconf doesn't quite recognize,
    # (or in my ignorance I can't specify it -- in any case Union support is weak), so do a dict to Any
    # "Leaf" elements of the nested dict must be Parameters
    inputs: Dict[str, Any]   = EmptyDictDefault()
    outputs: Dict[str, Any]  = EmptyDictDefault()
    defaults: Dict[str, Any] = EmptyDictDefault()

    backend: Optional[str] = None                 # backend, if not default

    dynamic_schema: Optional[str] = None          # function to call to augment inputs/outputs dynamically

    @staticmethod
    def flatten_schemas(io_dest, io, label, prefix=""):
        for name, value in io.items():
            name = f"{prefix}{name}"
            if not isinstance(value, Parameter):
                if not isinstance(value, (DictConfig, dict)):
                    raise SchemaError(f"{label}.{name} is not a valid schema")
                # try to treat as Parameter
                try:
                    value = OmegaConf.merge(ParameterSchema, value)
                    io_dest[name] = Parameter(**value)
                except Exception as exc0:
                    # try to treat as sub-schema
                    try:
                        Cargo.flatten_schemas(io_dest, value, label=label, prefix=f"{name}.")
                    # nested error from down the tree gets re-raises as is
                    except NestedSchemaError as exc:
                        raise
                    # all other exceptios, raise a NestedScheme error up
                    except Exception as exc:
                        raise NestedSchemaError(f"{label}.{name} is neither a parameter definition ({exc0}) nor a nested schema ({exc}")
        return io_dest

    def flatten_param_dict(self, output_params, input_params, prefix=""):
        for name, value in input_params.items():
            name = f"{prefix}{name}"
            if isinstance(value, (dict, DictConfig)):
                # if prefix.name. is present in schemas, treat as nested mapping
                if any(k.startswith(f"{name}.") for k in self.inputs_outputs):
                    self.flatten_param_dict(output_params, value, prefix=f"{name}.")
                    continue
            output_params[name] = value
        return output_params

    def __post_init__(self):
        self.fqname = self.fqname or self.name
        # flatten inputs/outputs into a single dict (with entries like sub.foo.bar)
        self.inputs = Cargo.flatten_schemas(OrderedDict(), self.inputs, "inputs")
        self.outputs = Cargo.flatten_schemas(OrderedDict(), self.outputs, "outputs")
        for name in self.inputs.keys():
            if name in self.outputs:
                raise DefinitionError(f"{name} appears in both inputs and outputs")
        self._inputs_outputs = None
        self._implicit_params = set()   # marks implicitly set values
        # flatten defaults and aliases
        self.defaults = self.flatten_param_dict(OrderedDict(), self.defaults)
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
            for io in self.inputs, self.outputs:
                for name, schema in list(io.items()):
                    if isinstance(schema, DictConfig):
                        try:
                            schema = OmegaConf.merge(ParameterSchema, schema)
                        except Exception  as exc:
                            raise SchemaError(f"error in dynamic schema for parameter 'name'", exc)
                        io[name] = Parameter(**schema)
        # add implicits, if resolved
        for name, schema in self.inputs_outputs.items():
            if schema.implicit is not None and type(schema.implicit) is not Unresolved:
                if name in params and name not in self._implicit_params:
                    raise ParameterValidationError(f"implicit parameter {name} was supplied explicitly")
                if name in self.defaults:
                   raise SchemaError(f"implicit parameter {name} also has a default value")
                params[name] = schema.implicit
                self._implicit_params.add(name)
        # assign unset categories
        for name, schema in self.inputs_outputs.items():
            schema.get_category()

        params = validate_parameters(params, self.inputs_outputs, defaults=self.defaults, subst=subst, fqname=self.fqname,
                                          check_unknowns=True, check_required=False, check_exist=False,
                                          create_dirs=False, ignore_subst_errors=True)        

        return params

    def validate_inputs(self, params: Dict[str, Any], subst: Optional[SubstitutionNS]=None, loosely=False):
        """Validates inputs.  
        If loosely is True, then doesn't check for required parameters, and doesn't check for files to exist etc.
        This is used when skipping a step.
        """
        assert(self.finalized)
        
        # check inputs
        params1 = validate_parameters(params, self.inputs, defaults=self.defaults, subst=subst, fqname=self.fqname,
                                                check_unknowns=False, check_required=not loosely, check_exist=not loosely, 
                                                create_dirs=not loosely)
        # check outputs
        params1.update(**validate_parameters(params, self.outputs, defaults=self.defaults, subst=subst, fqname=self.fqname, 
                                                check_unknowns=False, check_required=False, check_exist=False, 
                                                create_dirs=not loosely))
        return params1

    def validate_outputs(self, params: Dict[str, Any], subst: Optional[SubstitutionNS]=None, loosely=False):
        """Validates outputs. Parameter substitution is done. 
        If loosely is True, then doesn't check for required parameters, and doesn't check for files to exist etc.
        """
        assert(self.finalized)
        params.update(**validate_parameters(params, self.outputs, defaults=self.defaults, subst=subst, fqname=self.fqname,
                                                check_unknowns=False, check_required=not loosely, check_exist=not loosely))
        return params

    def make_substitition_namespace(self, params={}):
        from .substitutions import SubstitutionNS
        return SubstitutionNS(**params)

    def rich_help(self, tree, max_category=ParameterCategory.Optional):
        """Generates help into a rich.tree.Tree object"""
        if self.info:
            tree.add("Description:").add(Markdown(self.info))
        # adds tables for inputs and outputs
        for io, title in (self.inputs, "inputs"), (self.outputs, "outputs"):
            for cat in ParameterCategory:
                schemas = [(name, schema) for name, schema in io.items() if schema.get_category() == cat]
                if not schemas:
                    continue
                if cat > max_category:
                    subtree = tree.add(f"[dim]{cat.name} {title}: omitting {len(schemas)}[/dim]")
                    continue
                subtree = tree.add(f"{cat.name} {title}:")
                table = Table.grid("", "", "", padding=(0,2)) # , show_header=False, show_lines=False, box=rich.box.SIMPLE)
                subtree.add(table)            
                for name, schema in schemas: 
                    attrs = []
                    default = self.defaults.get(name, schema.default)
                    if schema.implicit:
                        attrs.append(f"implicit: {schema.implicit}")
                    if default is not None and not isinstance(default, Unresolved):
                        attrs.append(f"default: {default}")
                    if schema.choices:
                        attrs.append(f"choices: {', '.join(schema.choices)}")
                    info = []
                    schema.info and info.append(rich.markup.escape(schema.info))
                    attrs and info.append(f"[dim]\[{rich.markup.escape(', '.join(attrs))}][/dim]")
                    table.add_row(f"[bold]{name}[/bold]", 
                                  f"[dim]{rich.markup.escape(str(schema.dtype))}[/dim]", 
                                  " ".join(info))


ParameterPassingMechanism = Enum("ParameterPassingMechanism", "args yaml", module=__name__)


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

    _path: Optional[str] = None   # path to image definition yaml file, if any

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


    def summary(self, params=None, recursive=True, ignore_missing=False):
        lines = [f"cab {self.name}:"] 
        if params is not None:
            for name, value in params.items():
                # if type(value) is validate.Error:
                #     lines.append(f"  {name} = ERR: {value}")
                # else:
                lines.append(f"  {name} = {value}")
            lines += [f"  {name} = ???" for name, schema in self.inputs_outputs.items()
                        if name not in params and (not ignore_missing or schema.required)]
        return lines

    def rich_help(self, tree, max_category=ParameterCategory.Optional):
        tree.add(f"command: {self.command}")
        if self.image:
            tree.add(f"image: {self.image}")
        if self.virtual_env:
            tree.add(f"virtual environment: {self.virtual_env}")
        Cargo.rich_help(self, tree, max_category=max_category)

    def get_schema_policy(self, schema, policy, default=None):
        """Resolves a policy setting. If the policy is set here, returns it. If None and set in the cab,
        returns that. Else returns default value.
        """
        if getattr(schema.policies, policy) is not None:
            return getattr(schema.policies, policy)
        elif getattr(self.policies, policy) is not None:
            return getattr(self.policies, policy)
        else:
            return default

    def build_command_line(self, params: Dict[str, Any], subst: Optional[Dict[str, Any]] = None):
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

        return ([command] + args + self.build_argument_list(params)), venv


    def build_argument_list(self, params):
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

        value_dict = dict(**params)

        if self.parameter_passing is ParameterPassingMechanism.yaml:
            return [yaml.safe_dump(value_dict)]

        def get_policy(schema: Parameter, policy: str, default=None):
            return self.get_schema_policy(schema, policy, default)

        def stringify_argument(name, value, schema, option=None):
            key_value = get_policy(schema, 'key_value')
            if key_value:
                return f"{name}={value}"

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
                skip = get_policy(schema, 'skip') or (schema.implicit and get_policy(schema, 'skip_implicits', True))
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

            # default behaviour for unset skip_implicits is True
            skip_implicits = get_policy(schema, 'skip_implicits', True)

            if get_policy(schema, 'skip') or (schema.implicit and skip_implicits):
                continue

            key_value = get_policy(schema, 'key_value')

            # apply replacementss
            replacements = get_policy(schema, 'replace')
            if replacements:
                for rep_from, rep_to in replacements.items():
                    try:
                        name = name.replace(rep_from, rep_to)
                    except TypeError:
                        raise TypeError(f"Could not perform policy replacement for parameter [{name}] : {rep_from} => {rep_to}")

            option = (get_policy(schema, 'prefix') or "--") + (schema.nom_de_guerre or name)

            if schema.dtype == "bool":
                if key_value:
                    args += [f"{name}={value}"]
                else:
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



@dataclass
class Batch:
    scheduler: str = "slurm"
    cpus: int = 4
    mem: str = "128gb"
    email: Optional[str] = None

    def __init_cab__(self, cab: Cab, params: Dict[str, Any], subst: Optional[Dict[str, Any]], log: Any=None):
        self.cab = cab
        self.log = log
        self.args, self.venv = self.cab.build_command_line(params, subst)

