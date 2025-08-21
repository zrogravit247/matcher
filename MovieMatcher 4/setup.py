from setuptools import setup, find_packages

setup(
    name="movie-recommendation-app",
    version="1.0.0",
    description="A Flask-based movie recommendation application using TMDB API",
    python_requires=">=3.11",
    packages=find_packages(),
    install_requires=[
        "Flask>=3.0.0",
        "Flask-SQLAlchemy>=3.1.1",
        "requests>=2.31.0",
        "psycopg2-binary>=2.9.9",
        "gunicorn>=21.2.0",
        "email-validator>=2.1.0"
    ],

    include_package_data=True,
    zip_safe=False,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Framework :: Flask",
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    entry_points={
        'console_scripts': [
            'movie-rec-app=main:app',
        ],
    },
    package_data={
        '': ['templates/*', 'static/**/*'],
    },
)