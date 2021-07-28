from typing import List

logger = None

def set_logger(log):
    global logger
    logger = log


class Error(str):
    """A string that's marked as an error"""
    pass


class ScabhaBaseException(Exception):
    def __init__(self, message, log=None):
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

class CyclicSubstitutionError(SubstitutionError):
    def __init__(self, location: List[str], other_location: List[str]):
        self.location = ".".join(location)
        self.other_location = ".".join(other_location)
        super().__init__(f"'{{{self.location}}}' is a cyclic substition")

class SubstitutionErrorList(ScabhaBaseException):
    def __init__(self, *errors):
        self.errors = errors
        super().__init__(f"{len(errors)} substitution error(s)")
