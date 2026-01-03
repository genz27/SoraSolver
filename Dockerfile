FROM python:3.11-slim

# 安装 Chrome、Xvfb 和依赖
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    procps \
    # Xvfb 虚拟显示器
    xvfb \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# 安装 Chrome
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x start.sh

# 设置环境变量
ENV CHROME_PATH=/usr/bin/google-chrome-stable
ENV DOCKER_ENV=1
ENV DISPLAY=:99

# 并发配置
ENV MAX_WORKERS=3
ENV SEMAPHORE_LIMIT=3

EXPOSE 8005

CMD ["./start.sh"]
