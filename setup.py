from setuptools import setup
from pybind11.setup_helpers import Pybind11Extension

ext_modules = [
    Pybind11Extension("fft_cpp",
        ["fft_module.cpp"],
        libraries=["fftw3"],
        library_dirs=["/usr/lib/x86_64-linux-gnu"],
        include_dirs=["/usr/include"],
    ),
]

setup(
    name="fft_cpp",
    ext_modules=ext_modules,
)