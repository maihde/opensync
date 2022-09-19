import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="opensync",
    version="0.0.2",
    author="Michael Ihde",
    author_email="mike.ihde@gmail.com",
    description="An open-source flight log syncronization tool compatible with Garmin devices",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/maihde/opensync",
    project_urls={
        "Bug Tracker": "https://github.com/maihde/opensync/issues",
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GPLv3",
        "Operating System :: OS Independent",
    ],
    package_dir={"": "src"},
    packages=setuptools.find_packages(where="src"),
    data_files=[
        ('etc', ['cfg/opensync.conf', 'cfg/opensync.service', 'cfg/ups.sh']),
        ('dat', ['dat/optd_por_public_all.csv']),
    ],
    entry_points = {
        "console_scripts": [
            "opensync = opensync.daemon:main"
        ]
    },
    python_requires=">=3.9",
    install_requires=[
        "requests",
        "beautifulsoup4",
        "lxml",
        "tinydb",
        "pandas",
        "pySerial",
        "python-periphery",
        "note-python",
        "requests_toolbelt",
        "ConfigArgParse",
        "neobase"
    ],
)