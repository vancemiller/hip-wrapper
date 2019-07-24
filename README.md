# hip wrapper
This repository contains code for generating a shared library that intercepts calls to the AMD HIP runtime library.

## Quickstart:
    mkdir build
    cmake ..
    make
    # edit stubs
    make

## Notes:
Compile your HIP program to dynamically link the HIP library, not statically. 
To use the shim library: `LD_PRELOAD=/path/to/wrapper.so ./program`
