import dataclasses
import os, os.path, glob, yaml, re
from scabha import substitutions
from typing import *

from omegaconf import OmegaConf, ListConfig, DictConfig, MISSING
import pydantic
import pydantic.dataclasses

from .exceptions import Error, ParameterValidationError, SchemaError, SubstitutionErrorList
from .substitutions import SubstitutionNS, substitutions_from
from .types import File, Directory, MS


@dataclasses.dataclass
class Unresolved(object):
    value: str

    def __str__(self):
        return f"Unresolved({self.value})"


def join_quote(values):
    return "'" + "', '".join(values) + "'" if values else ""


def validate_schema(schema: Dict[str, Any]):
    """Checks a set of parameter schemas for internal consistency.

    Args:
        schema (Dict[str, Any]):   dict of parameter schemas

    Raises:
        SchemaError: [description]
    """

    pass



def validate_parameters(params: Dict[str, Any], schemas: Dict[str, Any], 
                        defaults: Optional[Dict[str, Any]] = None,
                        subst: Optional[SubstitutionNS] = None,
                        fqname: str = "",
                        check_unknowns=True,    
                        check_required=True,
                        check_exist=True,
                        expand_globs=True,
                        create_dirs=False,
                        ignore_subst_errors=False
                        ) -> Dict[str, Any]:
    """Validates a dict of parameter values against a given schema 

    Args:
        params (Dict[str, Any]):   map of input parameter values
        schemas (Dict[str, Any]):   map of parameter names to schemas. Each schema must contain a dtype field and a choices field.
        defaults (Dict[str, Any], optional): dictionary of default values to be used when a value is missing
        subst (SubsititionNS, optional): namespace to do {}-substitutions on parameter values
        fqname: fully-qualified name of the parameter set (e.g. "recipe_name.step_name"), used in error messages. If not given,
                errors will report parameter names only

        check_unknowns (bool): if True, unknown parameters (not in schema) raise an error
        check_required (bool): if True, missing parameters with required=True will raise an error
        check_exist (bool): if True, files with must_exist={None,True} in schema must exist, or will raise an error. 
                            If False, only files with must_exist=True must exist.
        expand_globs (bool): if True, glob patterns in filenames will be expanded.
        create_dirs (bool): if True, non-existing directories in filenames (and parameters with mkdir=True in schema) 
                            will be created.
        ignore_subst_errors (bool): if True, substitution errors will be ignored


    Raises:
        ParameterValidationError: parameter fails validation
        SchemaError: bad schema
        SubstitutionErrorList: list of substitution errors, if they occur

    Returns:
        Dict[str, Any]: validated dict of parameters

    TODO:
        add options to propagate all errors out (as values of type Error) in place of exceptions?
    """
    # define function for converting parameter name into "fully-qualified" name
    if fqname:
        mkname = lambda name: f"{fqname}.{name}"
    else:
        mkname = lambda name: name

    # check for unknowns
    if check_unknowns:
        for name in params:
            if name not in schemas:
                raise ParameterValidationError(f"unknown parameter '{mkname(name)}'")
    
    inputs = params.copy()

    # add missing defaults 
    defaults = defaults or {}
    for name, schema in schemas.items():
        if name not in params:
            if name in defaults:
                inputs[name] = defaults[name]
            elif schema.default is not None:
                inputs[name] = schema.default

    # perform substitution
    if subst is not None:
        with substitutions_from(subst, raise_errors=False) as context:
            for key, value in inputs.items():
                # do not substitute things that are not in the schema, or things for which substitutions are disabled
                if key not in schemas or schemas[key].policies.disable_substitutions:
                    continue
                inputs[key] = context.evaluate(value, location=[fqname, key] if fqname else [key])
                # ignore errors if requested
                if ignore_subst_errors and context.errors:
                    inputs[key] = Unresolved(context.errors)
                    context.errors = []
            if context.errors:
                raise SubstitutionErrorList(*context.errors)

    # split inputs into unresolved substitutions, and proper inputs
    unresolved = {name: value for name, value in inputs.items() if type(value) is Unresolved}
    inputs = {name: value for name, value in inputs.items() if type(value) is not Unresolved}

    # check that required args are present
    if check_required:
        missing = [mkname(name) for name, schema in schemas.items() 
                    if schema.required and inputs.get(name) is None and name not in unresolved]
        if missing:
            raise ParameterValidationError(f"missing required parameters: {join_quote(missing)}")

    # create dataclass from parameter schema
    validated = {}
    dtypes = {}
    fields = []

    # maps parameter names to/from field names. Fields have "_" not "-"
    name2field = {}
    field2name = {}

    for name, schema in schemas.items():
        value = inputs.get(name)
        if value is not None:
            try:
                dtypes[name] = dtype_impl = eval(schema.dtype, globals())
            except Exception as exc:
                raise SchemaError(f"invalid {mkname(name)}.dtype = {schema.dtype}")

            # sanitize name: dataclass won't take hyphens or periods
            fldname = re.sub("\W", "_", name)
            while fldname in field2name:
                fldname += "_"
            field2name[fldname] = name
            name2field[name] = fldname

            fields.append((fldname, dtype_impl))
            
            # OmegaConf dicts/lists need to be converted to standard containers for pydantic to take them
            if isinstance(value, (ListConfig, DictConfig)):
                inputs[name] = OmegaConf.to_container(value)

    dcls = dataclasses.make_dataclass("Parameters", fields)

    # convert this to a pydantic dataclass which does validation
    pcls = pydantic.dataclasses.dataclass(dcls)

    # check Files etc. and expand globs
    for name, value in inputs.items():
        # get schema from those that need validation, skip if not in schemas
        schema = schemas.get(name)
        if schema is None:
            continue
        # skip errors
        if value is None or isinstance(value, Error):
            continue
        dtype = dtypes[name]

        is_file = dtype in (File, Directory, MS)
        is_file_list = dtype in (List[File], List[Directory], List[MS])

        # must this file exist? Schema may force this check, otherwise follow the default check_exist policy
        must_exist = check_exist if schema.must_exist is None else schema.must_exist

        if is_file or is_file_list:
            # match to existing file(s)
            if type(value) is str:
                # try to interpret string as a formatted list (a list substituted in would come out like that)
                try:
                    files = yaml.safe_load(value)
                    if type(files) is not list:
                        files = None
                except Exception as exc:
                    files = None
                # if not, fall back to treating it as a glob
                if files is None:
                    files = sorted(glob.glob(value)) if expand_globs else [value]
            elif type(value) in (list, tuple):
                files = value
            else:
                raise ParameterValidationError(f"'{mkname(name)}={value}': invalid type '{type(value)}'")

            if not files:
                if must_exist:
                    raise ParameterValidationError(f"'{mkname(name)}={value}' does not specify any file(s)")
                else:
                    inputs[name] = [value] if is_file_list else value
                    continue

            # check for existence
            if must_exist: 
                not_exists = [f for f in files if not os.path.exists(f)]
                if not_exists:
                    raise ParameterValidationError(f"'{mkname(name)}': {','.join(not_exists)} doesn't exist")

            # check for single file/dir
            if dtype in (File, Directory, MS):
                if len(files) > 1:
                    raise ParameterValidationError(f"'{mkname(name)}': multiple files given ({value})")
                # check that files are files and dirs are dirs
                if os.path.exists(files[0]):
                    if dtype is File:
                        if not os.path.isfile(files[0]):
                            raise ParameterValidationError(f"'{mkname(name)}': {value} is not a regular file")
                    else:
                        if not os.path.isdir(files[0]):
                            raise ParameterValidationError(f"'{mkname(name)}': {value} is not a directory")
                inputs[name] = files[0]
                if create_dirs:
                    dirname = os.path.dirname(files[0])
                    if dirname:
                        os.makedirs(dirname, exist_ok=True)
            # else make list
            else:
                # check that files are files and dirs are dirs
                if dtype is List[File]:
                    if not all(os.path.isfile(f) for f in files if os.path.exists(f)):
                        raise ParameterValidationError(f"{mkname(name)}: {value} matches non-files")
                else:
                    if not all(os.path.isdir(f) for f in files if os.path.exists(f)):
                        raise ParameterValidationError(f"{mkname(name)}: {value} matches non-directories")
                inputs[name] = files
                if create_dirs:
                    for path in files:
                        dirname = os.path.dirname(path)
                        if dirname:
                            os.makedirs(dirname, exist_ok=True)

    # validate
    try:   
        validated = pcls(**{name2field[name]: value for name, value in inputs.items() if name in schemas and value is not None})
    except pydantic.ValidationError as exc:
        errors = [f"'{'.'.join(err['loc'])}': {err['msg']}" for err in exc.errors()]
        raise ParameterValidationError(', '.join(errors))

    validated = {field2name[fld]: value for fld, value in dataclasses.asdict(validated).items()}

    # check choice-type parameters
    for name, value in validated.items():
        schema = schemas[name]
        if schema.choices and value not in schema.choices:
            raise ParameterValidationError(f"{mkname(name)}: invalid value '{value}'")

    # check for mkdir directives
    if create_dirs:
        for name, value in validated.items():
            if schemas[name].mkdir:
                dirname = os.path.dirname(value)
                if dirname:
                    os.makedirs(dirname, exist_ok=True)

    # add in unresolved values
    validated.update(**unresolved)

    return validated
