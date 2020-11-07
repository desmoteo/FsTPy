import setuptools

# read the contents of your README file
from os import path
this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()    

setuptools.setup(
    name="fstpy", 
    version="0.0.2",
    author="Matteo Ferrabone",
    author_email="matteo.ferrabone@gmail.com",
    license='MIT',
    description="Bridging FTP and cloud storage",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/desmoteo/FsTPy",
    packages=setuptools.find_packages(),
    scripts=['scripts/fstpyd'],
    install_requires=[
      'fs',
      'pyftpdlib',
      'begins',
  ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        'Intended Audience :: Developers',
    ],
    python_requires='>=3.6',
)
