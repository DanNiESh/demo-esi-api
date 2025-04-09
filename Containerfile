FROM quay.io/nerc-images/demo-esi-api:latest

MAINTAINER Christopher Tate <computate@computate.org>

# By default, listen on port 8081
EXPOSE 8081/tcp

ENV FLASK_PORT=8081 \
  KAFKA_MAX_POLL_RECORDS='1' \
  KAFKA_MAX_POLL_INTERVAL_MS='3000000' \
  JAVA_HOME=/usr/lib/jvm/java-17-openjdk

# Set the working directory in the container
WORKDIR /usr/local/src/demo-esi-api

# Copy the dependencies file to the working directory
COPY requirements.txt /usr/local/src/demo-esi-api/

# Install any dependencies
RUN pip install -r requirements.txt

# Copy the content of the local src directory to the working directory
COPY . .

