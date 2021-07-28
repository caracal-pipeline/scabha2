
from validate import ValidateError
from .exceptions import SchemaError

def build_cab_parameters(cab):
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

    value_dict = dict(**cab.params)

    def get_policy(schema, policy):
        if schema.policies[policy] is not None:
            return schema.policies[policy]
        else:
            return cab.policies[policy]

    def stringify_argument(name, value, schema):
        if value in [None, False]:
            return None

        is_list = hasattr(value, '__iter__') and type(value) is not str
        format_policy = get_policy(schema, 'format')
        format_list_policy = get_policy(schema, 'format_list')

        if is_list:
            # apply formatting policies
            if format_list_policy:
                if len(format_list_policy) != len(value):
                    raise SchemaError("length of format_list_policy does not match length of '{name}'")
                value = [fmt.format(*value, **value_dict) for fmt in format_list_policy]
            elif format_policy:
                value = [format_policy.format(x, **value_dict) for x in value]
            else:
                value = [str(x) for x in value]
        else:
            if format_list_policy:
                value = [fmt.format(value, **value_dict) for fmt in format_list_policy]
                is_list = True
            elif format_policy:
                value = format_policy.format(value, **value_dict)
            else:
                value = str(value)

        if is_list:
            # check repeat policy and form up representation
            repeat_policy = get_policy(schema, 'repeat')
            if repeat_policy == "list":
                return list(value)
            elif type(repeat_policy) is str:
                return repeat_policy.join(value)
            elif repeat_policy is None:
                raise SchemaError(f"list-type parameter '{name}' does not have a repeat policy set")
            else:
                raise SchemaError(f"unknown repeat policy '{repeat_policy}'")
        else:
            return value

    # check for missing parameters and collect positionals

    pos_args = []

    for name, schema in cab.inputs_outputs:
        if schema.required and name not in value_dict:
            raise RuntimeError(f"required parameter '{name}' is missing")
        if name in value_dict:
            positional = get_policy(schema, 'positional')
            if positional:
                value = stringify_argument(name, value_dict[name], schema)
                if type(value) is list:
                    pos_args += value
                elif value is not None:
                    pos_args.append(value)
                value_dict.pop(name)
                
    # now check for optional parameters
    for name, value in value_dict.items():
        if name not in cab.inputs_outputs:
            raise RuntimeError(f"unknown parameter '{name}'")
        schema = cab.inputs_outputs[schema]

        # ignore None or False values, they are considered unset
        if value in [None, False]:
            continue

        prefix = get_policy(schema, 'prefix')
        if prefix is None:
            raise SchemaError(f"parameter prefix unset")

        replacements = get_policy(schema, 'replace')
        from scabha import logger
        logger.info(f"{name} {replacements}")
        for rep_from, rep_to in replacements.items():
            name = name.replace(rep_from, rep_to)

        option = prefix + name
        
        # True values map to a single option
        if value is True:
            args.append(option)
        else:
            value = stringify_argument(name, value, schema)
            if type(value) is list:
                for val in value:
                    args += [option, val]
            elif value is not None:
                args += [option, value]

    return args + pos_args
