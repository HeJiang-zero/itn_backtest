"""Compatibility metadata for the system pip bundled with macOS Python 3.9."""

from setuptools import find_packages, setup


setup(
    name="itn-backtest",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages("src"),
    install_requires=["numpy>=1.23", "pyarrow>=12", "PyYAML>=6", "matplotlib>=3.6"],
    extras_require={"dev": ["pytest>=7"]},
    entry_points={"console_scripts": ["itn-backtest=itn_backtest.cli:main"]},
)
