# 使用 Python 3.9 作为基础镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=app.py \
    FLASK_ENV=production \
    GUNICORN_CMD_ARGS="--bind=0.0.0.0:5000 --workers=1 --timeout=300"

# 复制项目文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir --index-url https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# 复制应用代码
COPY . .

# 创建上传目录并设置权限
RUN mkdir -p uploads && chmod 777 uploads

# 暴露端口
EXPOSE 5000

# 启动命令
CMD ["gunicorn", "app:app"] 