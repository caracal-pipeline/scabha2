#!/usr/bin/env python
from setuptools import setup
import os.path

requirements = ["pyyaml",
                "omegaconf",
                "click",
                "pydantic",
                "pyparsing",
                "pytest",
                "rich",
                "dill"
                ],

PACKAGE_NAME = "scabha"

__version__ = "2.0.0"
build_root = os.path.dirname(__file__)


def readme():
    """Get readme content for package long description"""
    with open(os.path.join(build_root, 'README.md')) as f:
        return f.read()

setup(name=PACKAGE_NAME,
      version=__version__,
      description="Parameter validation, substitution, configuration and other onboard services for Stimela",
      long_description=readme(),
      long_description_content_type="text/markdown",
      author="Oleg Smirnov & RATT",
      author_email="osmirnov@gmail.com",
      url="https://github.com/caracal-pipeline/scabha2",
      packages=["scabha"],
      package_data={"scabha": []},
      install_requires=requirements,
      scripts=[],
      classifiers=[],
      )
