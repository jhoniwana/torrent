# Use an official Python runtime as a parent image
FROM debian:buster-slim

# Set up archive repositories for Buster
RUN echo "deb http://archive.debian.org/debian/ buster main" > /etc/apt/sources.list && \
    echo "deb http://archive.debian.org/debian/ buster-updates main" >> /etc/apt/sources.list && \
    echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid-until

# Set the working directory in the container
WORKDIR /app

# Install ffmpeg for video splitting, and Python 3.9
RUN apt-get update && apt-get install -y ffmpeg python3.9 python3-pip && rm -rf /var/lib/apt/lists/*

# Copy the current directory contents into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Run bot.py when the container launches
CMD ["python3.9", "bot.py"]