# FinanceMailParser - 金融账单邮件解析工具

## 项目简介

FinanceMailParser 是一个用于自动化处理和解析金融账单邮件的Python工具。它可以连接到QQ邮箱,获取并解析各类金融账单,包括:

- 信用卡账单(支持多家银行)
    - 建设银行
    - 招商银行
    - 光大银行
    - 农业银行
- 支付宝账单
- 微信支付账单

解析后的数据会被统一整理成标准格式,方便后续分析和处理。

## 功能特点

- 支持QQ邮箱IMAP连接和邮件获取
- 自动识别并分类不同类型的账单邮件
- 支持多种账单格式解析:
    - HTML格式的信用卡账单
    - CSV格式的支付宝/微信支付账单
- 智能识别和过滤重复交易
- 支持按日期范围筛选交易记录
- 自动分类交易(如交通、餐饮等)
- 统一的数据输出格式
- 详细的日志记录

## 环境要求

- Python 3.10+
- 依赖包: requirements.txt

## 使用说明

### 第一步：下载账单

```
python run.py download --year 2024 --month 1 --log-level DEBUG
```

可选参数:
- `--year`: 指定年份(默认当年)
- `--month`: 指定月份(默认上月)
- `--statement-day`: 账单日(默认5号)
- `--log-level`: 日志级别(默认INFO)
- `--alipay-pwd`: 支付宝账单解压密码
- `--wechat-pwd`: 微信账单解压密码

### 第二步：解析已下载的账单

```
python run.py parse --log-level DEBUG
```

解析结果将保存为CSV格式,包含以下字段:
- 时间
- 分类
- 类型
- 金额
- 备注


## 配置说明

在首次运行前,需要配置以下信息:
1. QQ邮箱账号
2. QQ邮箱授权码(用于IMAP登录)
3. 可选:支付宝/微信账单解压密码

### 配置加密（主密码）

为避免敏感信息在本地/备份中以明文形式出现，本项目会将以下字段加密后写入 `config.yaml`：
- QQ 邮箱授权码（`email.qq.auth_code`）
- AI API Key（`ai.api_key`）

加密/解密使用环境变量 `FINANCEMAILPARSER_MASTER_PASSWORD` 作为主密码（不会写入磁盘）。示例：

```bash
export FINANCEMAILPARSER_MASTER_PASSWORD='your_master_password'
```

注意：
- 需要在启动程序/Streamlit 前设置该环境变量。
- `config.yaml` 可复制到其他机器使用，但必须提供相同的主密码才能解密。
- 若遗忘主密码，将无法解密已有配置，只能删除 `config.yaml` 后重新配置。

## 注意事项

- 请确保QQ邮箱已开启IMAP服务
- 建议定期备份已下载的邮件内容
- 账单文件可能包含敏感信息,请注意数据安全

## 常见问题

1. 登录失败
    - 检查邮箱账号和授权码是否正确
    - 确认IMAP服务是否已开启

2. 解析失败
    - 检查账单格式是否支持
    - 查看日志获取详细错误信息
