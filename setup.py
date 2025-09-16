from setuptools import setup, find_packages

setup(
    name="EZ-Panel",
    version="1.0",
    packages=find_packages(include=["ez_panel", "ez_panel.*"]),  # only ez_panel package
    include_package_data=True,  # works with MANIFEST.in to include non-Python files
    install_requires=[
        "Flask>=3.1.2",
    ],
    extras_require={
        "mdns": ["zeroconf>=0.39"],
    },
    entry_points={
        "console_scripts": [
            "EZ-Panel=ez_panel.run:main",   # requested CLI name
            "ez-panel=ez_panel.run:main",   # lowercase alias
            "ez_panel=ez_panel.run:main",   # underscore alias
            "ezpanel=ez_panel.run:main",    # short alias
            "EZ_Panel=ez_panel.run:main",    # underscore with caps alias
        ],
    },
    package_data={
        "ez_panel": [
            "templates/*.html",
            "static/css/*",
            "static/js/*",
            "static/images/*",
            "utils/*.py"
        ],
    },
    python_requires='>=3.12',
)
