from setuptools import setup, find_packages

setup(
    name="printer-craft",
    version="0.1.0",
    url="https://github.com/dharantej1/PrinterCraft",
    packages=find_packages(),
    install_requires=[],
    entry_points={
        "console_scripts": [
            "printer-craft=printer_craft.cli:main",
            "printcraft=printer_craft.cli:main",
        ],
    },
)
