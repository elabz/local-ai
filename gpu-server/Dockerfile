# GPU Server with llama.cpp for Pascal GPUs
# Optimized for P106-100 (6GB) and P104-100 (8GB)

FROM nvidia/cuda:11.8.0-devel-ubuntu22.04 AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    git \
    cmake \
    build-essential \
    python3 \
    python3-pip \
    libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Clone and build llama.cpp with CUDA support
WORKDIR /build
RUN git clone https://github.com/ggerganov/llama.cpp.git

WORKDIR /build/llama.cpp

# Create symlink for CUDA driver stub library
# Required for linking against CUDA Driver API in Docker build environment
RUN ln -s /usr/local/cuda/lib64/stubs/libcuda.so /usr/local/cuda/lib64/stubs/libcuda.so.1 && \
    ldconfig -n /usr/local/cuda/lib64/stubs

# Build with CUDA support for Pascal architecture (compute capability 6.1)
# P106-100 and P104-100 are based on GP106/GP104 (Pascal)
# Disable AVX/AMX instructions for Celeron processors without AVX support
# Uses GGML_ prefix (current naming convention) for CPU feature flags
RUN LD_LIBRARY_PATH=/usr/local/cuda/lib64/stubs:${LD_LIBRARY_PATH} \
    cmake -B build \
    -DGGML_CUDA=ON \
    -DCMAKE_CUDA_ARCHITECTURES="61" \
    -DLLAMA_CURL=ON \
    -DCMAKE_BUILD_TYPE=Release \
    -DGGML_NATIVE=OFF \
    -DGGML_AVX=OFF \
    -DGGML_AVX2=OFF \
    -DGGML_AVX512=OFF \
    -DGGML_AVX512_VBMI=OFF \
    -DGGML_AVX512_VNNI=OFF \
    -DGGML_AVX512_BF16=OFF \
    -DGGML_AMX_TILE=OFF \
    -DGGML_AMX_INT8=OFF \
    -DGGML_AMX_BF16=OFF \
    -DGGML_FMA=OFF \
    -DGGML_F16C=OFF \
    -DGGML_BMI2=OFF \
    -DCMAKE_CXX_FLAGS="-march=x86-64 -mno-bmi2" \
    -DCMAKE_C_FLAGS="-march=x86-64 -mno-bmi2" \
    -DCMAKE_EXE_LINKER_FLAGS="-Wl,-rpath-link,/usr/local/cuda/lib64/stubs"

RUN LD_LIBRARY_PATH=/usr/local/cuda/lib64/stubs:${LD_LIBRARY_PATH} \
    cmake --build build --config Release -j$(nproc)

# Runtime image
FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy llama.cpp binaries and shared libraries
COPY --from=builder /build/llama.cpp/build/bin/llama-server /usr/local/bin/
COPY --from=builder /build/llama.cpp/build/bin/llama-cli /usr/local/bin/
COPY --from=builder /build/llama.cpp/build/bin/llama-quantize /usr/local/bin/
COPY --from=builder /build/llama.cpp/build/bin/*.so* /usr/local/lib/

# Update library cache
RUN ldconfig

# Install Python dependencies for the wrapper API
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create model directory
RUN mkdir -p /models

# Environment variables
ENV MODEL_PATH=/models/model.gguf
ENV HOST=0.0.0.0
ENV PORT=8080
ENV N_GPU_LAYERS=99
ENV N_CTX=4096
ENV N_BATCH=512
ENV N_THREADS=4

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Expose ports
EXPOSE 8080

# Start the server
CMD ["python3", "server.py"]
