from setuptools import setup, find_packages

setup(
    name='cortex-lang',
    version='0.1.0',
    description='A programming language built natively for AI and RAG',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'cortex=cortex.cli:main',
        ],
    },
)
