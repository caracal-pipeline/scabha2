import pytest
import traceback
from scabha.exceptions import SubstitutionError
from scabha.substitutions import *
from omegaconf import OmegaConf 

def test_subst():

    x = OmegaConf.create()
    x.a = 1
    x.b = "{foo.a} not meant to be substituted here since x marked as not mutable"
    x.c = 3

    ns = SubstitutionNS(foo={})

    bar = SubstitutionNS()
    ns._add_("x", x, nosubst=True)
    ns._add_("bar", bar)
    
    ns.foo.zero = 0

    ns.foo.a = "{x.a}-{x.c}"
    ns.foo.b = "{foo.a}{{}}"
    ns.foo.c = "{bar.a}-{bar.x}-{bar.b}"
#    ns.foo['d/e'] = "x"

    ns.bar.a = 1
    ns.bar.b = "{foo.b}"
    ns.bar.c = "{foo.x} deliberately unresolved"
    ns.bar.c1 = "{foo.x.y.z} deliberately unresolved"
    ns.bar.b1 = "{bar.b}"

    # some deliberate cyclics
    ns.bar.d = "{bar.d}"
    ns.bar.e = "{bar.f}"
    ns.bar.f = "{bar.e}"


    with substitutions_from(ns, raise_errors=True) as context:
        assert context.evaluate("{bar.a}") == "1"
        assert context.evaluate("{bar.b}") == "1-3{}"
        assert context.evaluate("{bar.b1}") == "1-3{}"
        assert context.evaluate(["{x.a}-{x.c}", "{foo.a}{{}}"]) == ["1-3", "1-3{}"]
        assert context.evaluate(["{x.a}-{x.c}", {'y': "{foo.a}{{}}"}]) == ["1-3", {'y': "1-3{}"}]\
        
#        print(context.evaluate("{foo.d/e}"))

    with substitutions_from(ns, raise_errors=False) as context:
        val = context.evaluate("{bar.c}")
        # expect 1 error
        assert val == ''
        assert len(context.errors) == 1
        print(f"bar.c evaluates to type{type(val)}: '{val}'")
        print(f"error is (expected): {context.errors[0]}")

    with forgiving_substitutions_from(ns) as context:
        val = context.evaluate("{nothing}")
        assert val == ''   # '{nothing}' evaluates to '' in forgiving mode

    with forgiving_substitutions_from(ns, True) as context:
        val1 = context.evaluate("{nothing}")
        val2 = context.evaluate("{nothing.more}")
        print(f"errors (none expected): {context.errors}")
        assert not context.errors
        assert val1 == "(KeyError: 'nothing')" # '{nothing}' evaluates to '(error message)' in forgiving=True mode
        assert val2 == "(KeyError: 'nothing')" # '{nothing}' evaluates to '(error message)' in forgiving=True mode

    with forgiving_substitutions_from(ns, "XX") as context: # unknown substitutions evaluate to "XX"
        val = context.evaluate("{nothing}")
        assert val == 'XX'                            
        val = context.evaluate("{bar.c}")
        assert val == 'XX deliberately unresolved'    
        val = context.evaluate("{bar.c1}")
        assert val == 'XX deliberately unresolved'    
        val = context.evaluate("{bug.x} {bug.y}")
        assert val == 'XX XX'    

    with substitutions_from(ns) as context:
        val = context.evaluate("{bar.d}")
        val = context.evaluate("{bar.e}")
        val = context.evaluate("{foo.a:02d}")
        # expect 1 error
        assert len(context.errors) == 3
        for err in context.errors:
            print(f"expected error: {err}")

    with substitutions_from(ns, raise_errors=True) as context:
        try:
            val = context.evaluate("{bar.d}")
            assert val == "not allowed"
            print("{bar.d} is ", val)
        except CyclicSubstitutionError as exc:
            traceback.print_exc()

    try:
        context.evaluate("xxx")
        raise RuntimeError("exception should have been raised due to invalid substitution")
    except SubstitutionError as exc:
        print(f"Error as expected ({exc})")

    # test <<-substitutions
    
    with substitutions_from(ns) as context:
        p = OmegaConf.create()
        
        p.a  = "<< foo.a"
        p.b  = "<<foo.b" 
        p.c  = "<<foo.x?"
        
        p.d = "<< foo.a ?<<bar.a :<<bar.b !<<foo.c"
        p.e = "<< foo.zero ?<<bar.a :BB !<<foo.c"
        p.f = "<< foo.x? ?<<bar.a :<<bar.b !<<foo.c"
        p.g = "<< bar.a ?<<bar.b"
        p.h = "<< foo.zero :<<foo.c"
        p.i = "<< food?.x ?<<bar.a :<<bar.b !<<foo.c"

        try:
            errors = perform_ll_substitutions(ns, p, raise_exceptions=False)
            assert not errors
            assert p.a == context.evaluate("{foo.a}")
            assert p.b == context.evaluate("{foo.b}")
            assert 'c' not in p
            assert p.d == 1  # not "{bar.a}" because that's a string!
            assert p.e == "BB"
            assert p.f == context.evaluate("{foo.c}")
            assert p.g == context.evaluate("{bar.b}")
            assert p.h == context.evaluate("{foo.c}")
            assert p.i == context.evaluate("{foo.c}")
        except Exception as exc:
            print("Unexpected exception!")
            traceback.print_exc()
            raise
        
        # now some delibrate errors
        p = OmegaConf.create()
        p.a  = "<< foo.missing :bar.b ?foo.c"   # error
        p.b  = "<< foo.missing? :bar.b ?foo.c"  # no error, leave unset
        p.c  = "<< foo.x?"              # no error, leave unset 
        p.d  = "<< foo.x !foo.c"        # no error, ? is implicit due to !component
        p.e  = "<< missing?.x"          # no error, leave unset
        p.f  = "<< foo?.x !foo.c"       # error! foo is allowed to be missing, but not x
        errors = perform_ll_substitutions(ns, p, raise_exceptions=False)
        assert len(errors) == 2
        assert "b" not in p
        assert "c" not in p
        assert "e" not in p
        
        # and deliberate exceptions
        p = OmegaConf.create()
        p.a  = "<< foo.missing :bar.b ?foo.c"
        try:
            perform_ll_substitutions(ns, p, raise_exceptions=True)
            raise RuntimeError("exception should have been raised due to invalid substitution")
        except SubstitutionError as exc:
            print(f"Error as expected ({exc})")
            
        

if __name__ == "__main__":
    test_subst()

