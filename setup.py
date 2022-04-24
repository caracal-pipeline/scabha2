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
                "rich"
                ],

PACKAGE_NAME = "scabha"

__version__ = "2.0beta2"

setup(name=PACKAGE_NAME,
      version=__version__,
      description="Onboard services for passengers of Stimela (https://github.com/caracal-pipeline/stimela2) cabs",
      author="Oleg Smirnov & RATT",
      author_email="osmirnov@gmail.com",
      url="https://github.com/caracal-pipeline/scabha2",
      packages=["scabha"],
      package_data={"scabha": []},
      install_requires=requirements,
      scripts=[],
      classifiers=[],
      )
