from setuptools import setup, find_packages

setup(
    name="EZ-Panel",
    version="1.0",
    packages=find_packages(),  # finds ez_panel
    include_package_data=True,  # works with MANIFEST.in to include non-Python files
    install_requires=[
        "Flask>=3.1.2",
        # add any other Python dependencies here
    ],
    entry_points={
        "console_scripts": [
            "EZ-Panel=ez_panel.run:main",  # CLI command points to main()
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
