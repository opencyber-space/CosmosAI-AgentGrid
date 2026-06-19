#FROM python:latest
FROM python:3.11-slim
#FROM tempagent:squashed


WORKDIR /app

COPY requirements.txt /app

RUN apt-get update && apt-get install -y \
    git \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python3 --version
RUN pip3 install gepa==0.0.24
RUN pip3 install -r requirements.txt

# Set PYTHONPATH to include the /app directory
ENV PYTHONPATH="/app:${PYTHONPATH}"

COPY . /app/

RUN if [ -f /app/.env ]; then grep -E '^(AIGRID_MASTER|AIGRID_INFERENCE_SERVER_URL|POLICY_DB_URL|POLICY_DB_IP)=' /app/.env > /app/.env.tmp && mv /app/.env.tmp /app/.env; fi


#ENTRYPOINT [ "python3", "main.py" ]

# Accept an AGENT build-arg so the image can be tagged/parameterized at build time.
ARG AGENT=default
ENV AGENT=${AGENT}

# Copy an entrypoint script that will choose the runtime based on $AGENT
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]