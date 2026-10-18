# Upstream activation fixtures

These two unmodified scripts come from the Apache-2.0 licensed Conda-forge
`khronos-opencl-icd-loader-2024.10.24-hfd05255_2.conda` package, SHA-256
`245bd150a9f0b922dc34f173027631a20f18b009604d827a796d792a79bac178`.
They reproduce the native Windows installation failure for spaced prefixes.

Source: https://github.com/conda-forge/khronos-opencl-icd-loader-feedstock/tree/80ef539ea6232963e476eb9e616dd4a3379603dc
License: https://www.apache.org/licenses/LICENSE-2.0

The runtime repair is separate and hash-guarded. DLLs are not modified.
