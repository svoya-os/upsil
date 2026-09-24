from setuptools import setup, find_packages

setup(
    name='upsil-lang',
    version='0.1.0',
    description='A programming language built natively for AI and RAG',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'upsil=upsil.cli:main',
        ],
    },
)
