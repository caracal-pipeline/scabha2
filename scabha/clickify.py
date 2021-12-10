import itertools
from typing import *
import click

def clickify_parameters(schemas: Dict[str, Any]):

    decorator_chain = None
    for io in schemas.inputs, schemas.outputs:
        for name, schema in io.items():

            name = name.replace("_", "-")
            optname = f"--{name}"

            # sort out option type
            if schema.dtype == "bool":
                optname = f"{optname}/--no-{name}"
                dtype = bool
            elif schema.dtype == "str":
                dtype = str
            elif schema.dtype == "int":
                dtype = int
            elif schema.dtype == "float":
                dtype = float
            elif schema.dtype == "MS":
                dtype = click.Path(exists=True)

            # choices?
            if schema.choices:
                dtype = click.Choice(schema.choices)

            # aliases?
            optnames = [optname]
            if schema.abbreviation:
                optnames.append(f"-{schema.abbreviation}")

            deco = click.option(*optnames, type=dtype, 
                                default=schema.default, required=schema.required, metavar=schema.metavar,
                                help=schema.info)

            if decorator_chain is None:
                decorator_chain = deco
            else:
                decorator_chain = lambda x,deco=deco,chain=decorator_chain: chain(deco(x))

    return decorator_chain
