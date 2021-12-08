import sys
import pytest
from scabha import configuratt
from omegaconf import OmegaConf
from typing import *

def test_includes():
    conf = configuratt.load("testconf.yaml", use_sources=[])

    conf['nested'] = configuratt.load_nested(["test_nest_a.yml", "test_nest_b.yml", "test_nest_c.yml"], 
                                            typeinfo=Dict[str, Any], nameattr="_name")
#    conf['nested'] = configuratt.load_nested(["test_nest_a.yml", "test_nest_b.yml", "test_nest_c.yml"], typeinfo=List[str])

    OmegaConf.save(conf, sys.stderr)


if __name__ == "__main__":
    test_includes()