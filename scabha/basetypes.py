from dataclasses import field
from collections import OrderedDict


def EmptyDictDefault():
    return field(default_factory=lambda:OrderedDict())


def EmptyListDefault():
    return field(default_factory=lambda:[])
