from typing import List
import typing

logger = None

def set_logger(log):
    global logger
    logger = log


class Error(str):
    """A string that's marked as an error"""
    pass


class ScabhaBaseException(Exception):
    def __init__(self, message: str, nested: typing.Optional[Exception] = None, log=None):
        """Initializes exception object

        Args:
            message (str): error message
            nested (Optional[Exception]): Nested exception. Defaults to None.
            log (logger): if not None, logs the exception to the given logger
        """
        self.message = message
        self.nested = nested
        if nested is not None:
            message = f"{message}: {nested}"
        Exception.__init__(self, message)
        if log is not None:
            if not hasattr(log, 'error'):
                log = logger
            if log is not None:
                log.error(message)
        self.logged = log is not None

class SchemaError(ScabhaBaseException):
    pass

class DefinitionError(ScabhaBaseException):
    pass

class StepValidationError(ScabhaBaseException):
    pass

class CabValidationError(ScabhaBaseException):
    pass

class ParameterValidationError(ScabhaBaseException):
    pass

class SubstitutionError(ScabhaBaseException):
    pass

class UnsetError(ScabhaBaseException):
    def __init__(self, message, element, log=None):
        super().__init__(message, log)
        self.element = element

class ParserError(ScabhaBaseException):
    pass

class FormulaError(ScabhaBaseException):
    pass

class CyclicSubstitutionError(SubstitutionError):
    def __init__(self, location: List[str], other_location: List[str]):
        self.location = ".".join(location)
        self.other_location = ".".join(other_location)
        super().__init__(f"'{{{self.location}}}' is a cyclic substition")

class SubstitutionErrorList(ScabhaBaseException):
    def __init__(self, *errors):
        self.errors = errors
        super().__init__(f"{len(errors)} substitution error(s): {'; '.join(map(str, errors))}")
