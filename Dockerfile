# Focal is Ubuntu 20.04
FROM ubuntu:focal

ENV DEBIAN_FRONTEND=noninteractive 

# Install Chromium dependencies
# See https://github.com/miyakogi/pyppeteer/issues/14
RUN apt-get update && apt-get install -y --no-install-recommends \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
	fontconfig \
	fonts-ipafont-gothic \
	fonts-wqy-zenhei \    
	fonts-thai-tlwg \
	fonts-kacst \
	fonts-symbola \
	fonts-noto \
	fonts-freefont-ttf

RUN apt-get update && apt-get install -y --no-install-recommends \
    gconf-service \
    libasound2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libc6 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgcc1 \
    libgconf-2-4 \
    libgdk-pixbuf2.0-0 \
	libglib2.0-0 \
	libgtk-3-0 \
	libnspr4 \
	libpango-1.0-0 \
	libpangocairo-1.0-0 \
	libstdc++6 \
	libx11-6 \
	libx11-xcb1 \
	libxcb1 \
	libxcomposite1 \
	libxcursor1 \
	libxdamage1 \
	libxext6 \
	libxfixes3 \
	libxi6 \
	libxrandr2 \
	libxrender1 \
	libxss1 \
	libxtst6 \
	ca-certificates \
	fonts-liberation \
	libappindicator1 \
	libnss3 \
	lsb-release \
	xdg-utils\
    wget

# (Optional) Install XVFB if there's a need to run browsers in headful mode
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    x11vnc

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    dumb-init

# Development tools: python, git
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-venv \
    python3-pip \
    git

# Install Chrome
RUN curl -sSL https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] https://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable 

# RUN apt-get update && apt-get install -y --no-install-recommends google-chrome-stable 

# Add user so we don't need --no-sandbox in Chromium
RUN groupadd chrome && useradd -g chrome -s /bin/bash -G audio,video chrome \
    && mkdir -p /home/chrome/Downloads \
    && chown -R chrome:chrome /home/chrome

RUN python3 -m pip install \
    setuptools \
    flake8 \
    black \
    pytest \
    pytest-benchmark \
    pytest-asyncio

COPY requirements.txt ./
RUN python3 -m pip install -r requirements.txt

RUN python3 -m pip freeze --local --all

# Run everything after as non-privileged user.
USER chrome

WORKDIR /home/chrome

# Load ads servers
# https://groups.google.com/a/chromium.org/g/headless-dev/c/G1u6SGeq7nw?pli=1
RUN curl https://winhelp2002.mvps.org/hosts.txt > ./ads-servers.txt

# https://stackoverflow.com/questions/35134713/disable-cache-for-specific-run-commands
ARG CACHEBUST=1
RUN echo date > .bust && curl https://raw.githubusercontent.com/larytet-py/ads_hosts/master/hosts.txt > ./ads-servers.he.txt

COPY ./setup.cfg .
RUN mkdir -p ./src
COPY src/. ./src/

RUN black --diff src/.
RUN flake8 --config=./setup.cfg src/.
RUN python3 --version
RUN pytest --benchmark-disable --capture=no --verbose --maxfail=1 src/.

EXPOSE 5900
WORKDIR /home/chrome
COPY start.sh ./
CMD ["./start.sh"]
