"""rosetta-flow: open, on-prem auditor for AI-agent traces, built with Apertus."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("rosetta-flow")
except PackageNotFoundError:
    __version__ = "0.0.0+local"
