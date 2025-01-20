class Config:
    # Flask 应用配置
    SECRET_KEY = 'dev'  # 在生产环境中应该使用强随机密钥
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 限制上传文件大小为 5MB

    # 文件上传配置
    UPLOAD_FOLDER = 'uploads'
    ALLOWED_EXTENSIONS = {'xlsx'}

    # 代理配置
    PREFERRED_URL_SCHEME = 'http'
    APPLICATION_ROOT = '/attendance' 