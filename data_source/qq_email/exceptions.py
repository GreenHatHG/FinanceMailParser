class QQEmailError(Exception):
    """QQ邮件处理基础异常类"""

    pass


class LoginError(QQEmailError):
    """登录失败异常"""

    pass


class ParseError(QQEmailError):
    """解析失败异常"""

    pass
