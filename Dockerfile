FROM python:3.12-slim

WORKDIR /app

# pip 国内镜像加速
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn

# curl：健康检查；glib/pango/cairo：WeasyPrint PDF 导出所需原生库
# apt 走阿里云镜像（国内构建提速；海外源可用时可改回 deb.debian.org）
RUN sed -i "s/deb.debian.org/mirrors.aliyun.com/g" /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libffi8 \
        libglib2.0-0 \
        shared-mime-info \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=120 -r requirements.txt \
    && pip install --no-cache-dir psycopg2-binary

COPY . .

EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
