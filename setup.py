#!/usr/bin/env python
from setuptools import setup

requirements = ["pyyaml",
                "nose>=1.3.7",
                "omegaconf",
                "click",
                "pydantic",
                "ruamel.yaml",
                "pyparsing",
                "pytest",
                "rich",
                "dill"
                ],

PACKAGE_NAME = "scabha"

__version__ = "2.0.0"

def readme():
    """Get readme content for package long description"""
    with open(os.path.join(build_root, 'README.rst')) as f:
        return f.read()

setup(name=PACKAGE_NAME,
      version=__version__,
      description="Parameter validation, substitution, configuration and other onboard services for Stimela",
      long_description=readme(),
      long_description_content_type="text/x-rst",
      author="Oleg Smirnov & RATT",
      author_email="osmirnov@gmail.com",
      url="https://github.com/caracal-pipeline/scabha2",
      packages=["scabha"],
      package_data={"scabha": []},
      install_requires=requirements,
      scripts=[],
      classifiers=[],
      )
