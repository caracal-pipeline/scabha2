#!/usr/bin/env python
import os
import sys
from setuptools import setup
import glob

requirements = ["pyyaml",
                "nose>=1.3.7",
                "future-fstrings",
                "omegaconf",
                "pytest"
                ],

PACKAGE_NAME = "scabha"
__version__ = "0.4.0"

setup(name=PACKAGE_NAME,
      version=__version__,
      description="Onboard services for passengers of Stimela (https://github.com/ratt-ru/Stimela) cabs",
      author="Oleg Smirnov & RATT",
      author_email="osmirnov@gmail.com",
      url="https://github.com/ratt-ru/scabha",
      packages=["scabha"],
      package_data={"scabha": []},
      install_requires=requirements,
      scripts=[],
      classifiers=[],
      )
