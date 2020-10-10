#!/usr/bin/env python3

import os
from setuptools import setup, find_packages
from . import __version__


def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


setup(
    name='transferwise-importer',
    version=__version__,
    description='TransferWise to Firefly III connector',
    # long_description=read('README'),
    url='https://github.com/psedge/firefly-importers',
    author='psedge',
    license='MIT',
    keywords='firefly transferwise',
    packages=find_packages(exclude=('lambda.py')),
    include_package_data=True,
    install_requires=[],
    extras_require={},
    classifiers=[],
)
