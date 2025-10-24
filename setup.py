#!/usr/bin/env python3
"""
G-Assist Setup Script

Main setup script for installing G-Assist and its components.
"""

import os
from pathlib import Path

try:
    from setuptools import setup, find_packages
except ImportError as exc:
    raise ImportError(
        "setuptools is required to install G-Assist. "
        "Please install it with: pip install setuptools"
    ) from exc

# Read the README
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

# Core dependencies
install_requires = [
    "psutil>=5.8.0",
    "tqdm>=4.62.0",
]

# Platform-specific dependencies
if os.name == 'nt':  # Windows
    install_requires.append("pywin32>=302")

setup(
    name="g-assist",
    version="0.1.0",
    author="NVIDIA Corporation",
    author_email="g-assist@nvidia.com",
    description="G-Assist: AI Assistant for RTX and Blackwell GPUs",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/nvidia/g-assist",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: System :: Hardware",
    ],
    python_requires=">=3.8",
    install_requires=install_requires,
    extras_require={
        "dev": [
            "pytest>=6.0",
            "black>=21.0",
            "flake8>=3.9",
            "mypy>=0.900",
        ],
        "gui": [
            "flask>=2.0",
            "flask-cors>=3.0",
            "colorama>=0.4",
        ],
    },
    entry_points={
        "console_scripts": [
            "g-assist-core=core.g_assist_core:main",
            "g-assist=core.g_assist_core:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
