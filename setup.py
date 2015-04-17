#!/usr/bin/env python

import os

from setuptools import setup


def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup(
    name="statprof-smarkets",
    version="0.2.0",
    author="Smarkets",
    author_email="support@smarkets.com",
    description="Statistical profiling for Python",
    license='LGPL 2, see LICENSE file',
    keywords=["profiling", "statistical profiling", "statprof"],
    url="https://github.com/smarkets/statprof",
    py_modules=['statprof'],
    long_description=read('README.rst'),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Topic :: Utilities",
        "License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)",
        "Programming Language :: Python",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 3",
    ],
    install_requires=[
        'six>=1.5.0',
    ],
    zip_safe=False,
)
