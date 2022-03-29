from pyparsing import *
from pyparsing import common
# Forward, Group, Word, Optional, alphas, alphanums, nums, ZeroOrMore, Literal, sglQuotedString, dblQuotedString
from rich import print

def test_parser():
    from scabha.evaluator import construct_parser

    expr = construct_parser()

    a = expr.parseString("a.b", parse_all=True)
    print(a.dump())

    a = expr.parseString("IFSET(a.b)", parse_all=True)
    print(a.dump())

    a = expr.parseString("a==b", parse_all=True)
    print(a.dump())


    a = expr.parseString("(a==0)==IF(a==0,1,2,3)", parse_all=True)
    print(a.dump())

    a = expr.parseString("IFSET(a.b, (a==0)==(a==0),(a!=b))", parse_all=True)
    print(a.dump())

    a = expr.parse_string("IF((previous.x+1)*previous.x == 2, previous.x == 0, previous.y == 0)", parse_all=True)

    expr.runTests("""
        (a==0)
        ((a==0)==(a==0))
        IFSET(a.b)
        IFSET(a.b, (a==0)==(a==0),(a!=b))
        IF((previous.x+1)*previous.x == 2, previous.x is 0, previous.y is not 0)
        IF((-previous.x+1)*previous.x == 0, previous.x is 0, previous.y < 0)
        a. b
        """)

#    a = expr.parse_string("((a.x))")
    



if __name__ == "__main__":
    test_parser()