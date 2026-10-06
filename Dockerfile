# Use Python 3.13 slim image as base
FROM python:3.13-slim
# Set working directory
WORKDIR /app
# Compose passes the predefined proxy build-args (HTTP_PROXY, http_proxy, ...).
# Docker injects them only into RUN and keeps them out of image metadata.
# Do not copy them into ENV: a proxy URL often contains credentials.
# Install system dependencies required for geospatial libraries
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    libspatialindex-dev \
    && rm -rf /var/lib/apt/lists/*
# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Copy application code (.env is excluded by .dockerignore)
COPY . .
# Set environment variables
ENV PYTHONPATH=/app
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
# Expose port
EXPOSE 8501
# Run the application
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
