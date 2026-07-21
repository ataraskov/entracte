from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("entracte")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
