FROM python:3.10-slim

WORKDIR /app

# Install system dependencies required for some Python packages (e.g. compiling uvloop/orjson)
RUN apt-get update && apt-get install -y \
    build-essential \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create a symlink for the SQLite database so it can be mounted via a named volume
# The app expects trading_app.db in the root, but we want it stored in a persistent /data directory
RUN mkdir -p /data && touch /data/trading_app.db && ln -sf /data/trading_app.db /app/trading_app.db

# Expose the API port
EXPOSE 8000

# Set environment variables for production
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Kolkata

# Command to run the application using Uvicorn with the high-performance uvloop
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "uvloop"]
