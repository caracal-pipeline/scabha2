import pytest
import traceback
from scabha.exceptions import SubstitutionError
from scabha.substitutions import CyclicSubstitutionError, SubstitutionNS, substitutions_from, forgiving_substitutions_from
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

    ns.foo.a = "{x.a}-{x.c}"
    ns.foo.b = "{foo.a}{{}}"
    ns.foo.c = "{bar.a}-{bar.x}-{bar.b}"

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
        assert context.evaluate(["{x.a}-{x.c}", {'y': "{foo.a}{{}}"}]) == ["1-3", {'y': "1-3{}"}]

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
        raise RuntimeError("exception not raised out of context")
    except SubstitutionError as exc:
        print(f"Error as expected ({exc})")

    


if __name__ == "__main__":
    test_subst()

