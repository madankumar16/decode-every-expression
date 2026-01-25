# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies for OpenCV and other libs
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Create directory for captures and set permissions (HF runs as user 1000)
RUN mkdir -p face_emotion_detection/webapp/static/captures && \
    chmod -R 777 face_emotion_detection/webapp/static/captures

# Expose the port the app runs on
EXPOSE 7860

# Command to run the application
# We use the webapp directory as the starting point
WORKDIR /app/face_emotion_detection/webapp
CMD ["python", "app.py"]
