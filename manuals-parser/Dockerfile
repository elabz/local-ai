# Manuals-parser — batch PDF→structured-document conversion for the manuals
# pilot. Three arms: Docling (primary), PaddleOCR PP-StructureV3 (scanned
# subset), and page images through our own LiteLLM proxy. Every engine is
# licence-clean in both code and weights; see README § Licensing.
#
# Target hardware: PEA's NVIDIA P104-100 (Pascal, sm_61), 8GB. Same CUDA 12.1 +
# torch cu121 base as gpu-server/dino-embed, which is the proven Pascal build in
# this repo. Whether the conversion stacks actually accelerate on sm_61 is an
# open pilot question — convert.py reports the device it ran on, and the image
# runs CPU-only unmodified if CUDA is absent or unusable.
#
# Unlike gpu-server/* this is a batch container, not a server: no ports, no
# healthcheck, no metrics endpoint. It is invoked with a command.

FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# poppler-utils + tesseract back the OCR path on scanned documents;
# libgl1/libglib2.0-0 are the usual OpenCV runtime deps pulled in by the
# layout models.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    poppler-utils \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-deu tesseract-ocr-fra \
    tesseract-ocr-spa tesseract-ocr-ita \
    tesseract-ocr-jpn tesseract-ocr-jpn-vert \
    libgl1 libglib2.0-0 \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip3 install --upgrade pip && \
    pip3 install torch==2.4.1 torchvision==0.19.1 \
        --index-url https://download.pytorch.org/whl/cu121

COPY requirements.txt .
RUN pip3 install -r requirements.txt

COPY . .

# Model weights (layout/OCR/table models) are cached into a mounted volume so
# repeat batch runs do not re-download them.
#
# DOCLING_ARTIFACTS_PATH is deliberately NOT set. Docling reads it as "the
# models are already here", not "download them here", so pointing it at an empty
# volume aborts every conversion with `artifacts_path ... is not valid` before
# any download is attempted (found in pilot task 1.4, first live run).
# HF_HOME/HF_HUB_CACHE already land the weights in the same mounted volume, so
# the first run fetches and every later run reuses. To pre-seed an offline host,
# run `docling-tools models download -o /models/docling` into the volume and set
# DOCLING_ARTIFACTS_PATH at run time.
RUN mkdir -p /models
ENV HF_HOME=/models \
    HF_HUB_CACHE=/models \
    PADDLE_PDX_MODEL_SOURCE=huggingface \
    PADDLE_PDX_CACHE_HOME=/models/paddle

# The VLM arm talks to the LiteLLM proxy we already run; supply these at run
# time. No key is baked into the image.
ENV LITELLM_BASE_URL="" \
    LITELLM_API_KEY="" \
    LITELLM_VLM_MODEL=gemini-3-flash-preview

# Corpus in, results out — both bind-mounted at run time.
VOLUME ["/corpus", "/out", "/models"]

ENTRYPOINT ["python3", "convert.py"]
CMD ["--help"]
