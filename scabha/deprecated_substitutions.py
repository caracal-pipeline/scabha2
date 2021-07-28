import re
from collections import OrderedDict
from scabha.cargo import EmptyDictDefault
from dataclasses import dataclass
from contextlib import contextmanager
from typing import Any, Dict, Optional, Union

from .validate import Error
from .exceptions import SubstitutionError


# thanks to https://gist.github.com/bgusach/a967e0587d6e01e889fd1d776c5f3729
def multireplace(string, replacements, ignore_case=False):
    """
    Given a string and a replacement map, it returns the replaced string.
    :param str string: string to execute replacements on
    :param dict replacements: replacement dictionary {value to find: value to replace}
    :param bool ignore_case: whether the match should be case insensitive
    :rtype: str
    """
    # If case insensitive, we need to normalize the old string so that later a replacement
    # can be found. For instance with {"HEY": "lol"} we should match and find a replacement for "hey",
    # "HEY", "hEy", etc.
    if ignore_case:
        def normalize_old(s):
            return s.lower()

        re_mode = re.IGNORECASE

    else:
        def normalize_old(s):
            return s

        re_mode = 0

    replacements = {normalize_old(key): val for key, val in replacements.items()}
    
    # Place longer ones first to keep shorter substrings from matching where the longer ones should take place
    # For instance given the replacements {'ab': 'AB', 'abc': 'ABC'} against the string 'hey abc', it should produce
    # 'hey ABC' and not 'hey ABc'
    rep_sorted = sorted(replacements, key=len, reverse=True)
    rep_escaped = map(re.escape, rep_sorted)
    
    # Create a big OR regex that matches any of the substrings to replace
    pattern = re.compile("|".join(rep_escaped), re_mode)
    
    # For each match, look up the new string in the replacements, being the key the normalized old string
    return pattern.sub(lambda match: replacements[normalize_old(match.group(0))], string)

def _fqname(parent_names, name):
    return '.'.join((parent_names or []) + [name])


@contextmanager
def forgive_errors(error_types={AttributeError}, mode=""):
    previous = SubstitutionNamespace._forgiving_.copy()
    for err in error_types:
        SubstitutionNamespace._forgiving_[err] = mode
    try:
        yield True
    finally:
        SubstitutionNamespace._forgiving_ = previous

def forgive_most_errors(mode=""):
    return forgive_errors({AttributeError, TypeError, ValueError}, mode="")


class SubstitutionNamespace(OrderedDict):
    """Implements a namespace that can do {}-substitutions on itself
    """
    @dataclass
    class Properties(object):
        mutable: bool = True
        updated: bool = False
        forgiving: dict = EmptyDictDefault

    _default_prop_ = Properties()

    # forgiving mode for various errors. If False/None, raise AttributeError. If True, return "{attr}"" when attribute is not known. If string, return given string
    _forgiving_ = {}

    def __init__(self, **kw):
        """Initializes the namespace. Keywords are _add_'ed as items in the namespace
        """
        super().__setattr__('_props_', SubstitutionNamespace.Properties())
        super().__setattr__('_child_props_', {})
        super().__setattr__('_forgave_', set())
        SubstitutionNamespace._update_(self, **kw)

    def copy(self):
        newcopy = SubstitutionNamespace()
        OrderedDict.__setattr__(newcopy, '_props_', self._props_)
        OrderedDict.__setattr__(newcopy, '_child_props_', self._child_props_.copy())
        OrderedDict.__setattr__(newcopy, '_forgave_', self._forgave_.copy())
        for key, value in self.items():
            OrderedDict.__setitem__(newcopy, key, value)
        return newcopy

    def _update_(self, **kw):
        """Updates items in the namespace using _add_()
        """
        for name, value in kw.items():
            SubstitutionNamespace._add_(self, name, value)

    def _merge_(self, ns):
        """Recursively merges in one namespace into another
        """
        for name, value in ns.items():
            if name not in self:
                SubstitutionNamespace._add_(self, name, value)
            else:
                old_value = super().get(name)
                if isinstance(old_value, SubstitutionNamespace) and \
                    isinstance(value, (dict, OrderedDict, SubstitutionNamespace)):
                    old_value._merge_(**value)
                else:
                    SubstitutionNamespace._add_(self, name, value)

    def _add_(self, k: str, v: Any, forgiving={}, mutable=True):
        """Adds an item to the namespace.

        Args:
            k (str): item key
            v (Any): item value. A dict or OrderedDict value becomes a SubstitutionNamespace automatically
            forgiving (bool, optional): If True, sub-namespace is "forgiving" with references to missing items,
                returning "(name)" for ns.name if name is missing. If False, such references result in an AttributeError.
                Default is False.
            mutable (bool, optional): If False, sub-namespace is immutable and not will not have substitutions done inside it. Defaults to True.
        """
        if forgiving is True:
            forgiving = {AttributeError: True}
        props = SubstitutionNamespace.Properties(mutable=mutable, forgiving=forgiving)
        if type(v) in (dict, OrderedDict):
            v = SubstitutionNamespace(**v)
        if isinstance(v, SubstitutionNamespace):
            OrderedDict.__setattr__(v, '_props_', props)
        self._child_props_[k] = props
        super().__setitem__(k, v)

    def __setattr__(self, name: str, value: Any) -> None:
        SubstitutionNamespace._add_(self, name, value)

    def __setitem__(self, k: str, v: Any) -> None:
        SubstitutionNamespace._add_(self, k, v)

    def __forgiving_mode__ (self, err):
        forgive = SubstitutionNamespace._forgiving_.get(err) 
        if forgive is None:
            forgive = self._props_.forgiving.get(err)
        return forgive

    def __getattr__(self, name: str) -> Any:
        if name in self:
            return super().get(name)
        else:
            # if global mode is set, overrides local mode
            forgive = self.__forgiving_mode__(AttributeError)
            # if string, or True, return forgive-value
            if type(forgive) is str or forgive:
                self._forgave_.add(name)
                return forgive if type(forgive) is str else f"(name)"  
            else:
                raise AttributeError(name)

    def _substitute_(self, subst: Optional['SubstitutionNamespace'] = None, parent_names=[]):
        """Recursively substitutes {}-strings within this namespace

        Args:
            subst (SubstitutionNamespace, optional): Namespace used to look up substitutions. Defaults to self.
            parent_names (list): list of parent names (including name of this namespace, if any)

        Returns:
            SubstitutionNamespace, updated, unresolved: output namespace (same as self if copy=False), count of updates, list of unresolved substitutions
        """
        updated = 0
        unresolved = []
        output = self
        # loop over parameters and find ones to substitute
        for name, value in super().items():
            props = self._child_props_[name]
            updated1 = 0
            unresolved1 = []
            # substitute strings
            if isinstance(value, str) and not isinstance(value, Error) and "{" in value:
                # format string value
                try:
                    # protect "{{" and "}}" from getting converted to a single brace by pre-replacing them
                    newvalue = multireplace(value, {'{{': '\u00AB', '}}': '\u00BB'})
                    newvalue = newvalue.format(**(subst or output))
                    newvalue = multireplace(newvalue, {'\u00AB': '{{', '\u00BB': '}}'})
                    updated1 = int(value != newvalue)
                except Exception as exc:
                    forgive = self.__forgiving_mode__(type(exc))
                    if type(forgive) is str:
                        newvalue = forgive
                        updated1 = int(value != newvalue)
                    elif forgive:
                        newvalue = "(name)"
                        updated1 = int(value != newvalue)
                    else:
                        location = f"{'.'.join(parent_names + [name])}='{value}'"
                        if type(exc) is AttributeError:
                            err = SubstitutionError(f"'{{{' '.join(exc.args)}}}' unresolved in {location}")
                        else:
                            err = SubstitutionError(f"{exc} in {location} ({type(exc)})")
                        newvalue = err
                        unresolved1 = [err] 
                        updated1 = 1
            # else substitute into mutable sub-namespaces
            elif isinstance(value, SubstitutionNamespace) and props.mutable:
                newvalue, updated1, unresolved1 = value._substitute_(subst or output, parent_names=parent_names + [name])
            elif isinstance(value, Exception):
                unresolved1 = [value]
            # has something changed? make copy of ourselves if so
            if updated1:
                if output is self:
                    output = self.copy()
                OrderedDict.__setitem__(output, name, newvalue)
            # update counters
            updated += updated1
            unresolved += unresolved1

        return output, updated, unresolved

    def _clear_forgivens_(self):
        super().__setattr__('_forgave_', set())
        for child in self.values():
            if isinstance(child, SubstitutionNamespace):
                child._clear_forgivens_()

    def _collect_forgivens_(self, name: Optional[str] = None):
        own_name = name or "."
        result = [f"{own_name}.{key}" for key in self._forgave_]
        for child_name, child in self.items():
            if isinstance(child, SubstitutionNamespace):
                result += child._collect_forgivens_(f"{name}.{child_name}" if name is not None else child_name)
        return result

    def _finalize_braces_(self):
        output = self
        for name, value in self.items():
            props = self._child_props_[name]
            updated = False
            if isinstance(value, SubstitutionNamespace) and props.mutable:
                newvalue = value._finalize_braces_()
                updated = newvalue is not value
            elif isinstance(value, str):
                newvalue = value.format()  # this converts {{ and }} to { and }
                updated = newvalue != value
            if updated:
                if output is self:
                    output = self.copy()
                OrderedDict.__setitem__(output, name, newvalue)
        return output

    def _print_(self, prefix="", printfunc=print):
        for name, value in self.items():
            if name.startswith("_") or name.endswith("_"):
                continue
            if isinstance(value, SubstitutionNamespace):
                printfunc(f"{prefix}{name}:")
                value._print_(prefix + "  ")
            elif isinstance(value, Exception):
                printfunc(f"{prefix}{name}: ERR: {value}")
            else:
                printfunc(f"{prefix}{name}: {value}")


def self_substitute(ns: SubstitutionNamespace, name: Optional[str] = None, debugprint = None):
    """Resolves {}-substitutions within a namespace.

    Args:
        ns (SubstitutionNamespace): namespace to do substitutions in.
        name (Optional[str], optional): name of this namespace, used in messages.
        debugprint (callable, optional): if set, function used to print debug messages.

    Raises:
        SubstitutionError: [description]

    Returns:
        SubstitutionNamespace: copy of namespace with substitutions in it. Will be the same as ns if no substitutions done
    """
    ns._clear_forgivens_()

    debugprint and debugprint("--- before substitution ---")
    debugprint and ns._print_(printfunc=debugprint, prefix="  ")

    # repeat as long as values keep changing, but qut after 10 cycles in case of infinite cross-refs
    for i in range(10):
        ns, updated, unresolved = ns._substitute_()
        debugprint and debugprint(f"--- iteration {i} updated {updated} unresolved {unresolved} ---")
        if not updated:
            break 
        debugprint and ns._print_(printfunc=debugprint, prefix="  ")
    else:
        raise SubstitutionError("recursion limit exceeded while evaluating {}-substitutions. This is usally caused by cyclic (cross-)substitutions.")

    # clear up "{{"s
    debugprint and debugprint(f"--- finalizing curly braces ---")
    ns = ns._finalize_braces_()
    debugprint and ns._print_(printfunc=debugprint, prefix="  ")

    return ns, unresolved, ns._collect_forgivens_(name)


# def copy_updates(src: SubstitutionNamespace, dest: Dict[str, Any]):
#     for name, value in src.items():
#         props = src._child_props_[name]
#         if props.updated:
#             dest[name] = value
