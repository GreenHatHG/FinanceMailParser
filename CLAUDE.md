# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

FinanceMailParser 是一个金融账单邮件解析工具，用于自动化处理和解析来自QQ邮箱的金融账单。项目支持信用卡账单（多家银行）、支付宝账单和微信支付账单的解析，并将数据统一整理成标准格式。

## 核心命令

### 环境设置
```bash
# 安装依赖
pip install -r requirements.txt

# 设置主密码（用于配置加密）
export FINANCEMAILPARSER_MASTER_PASSWORD='your_master_password'
```

### 启动应用
```bash
# 启动 Streamlit Web 界面
streamlit run ui/app.py

# UI 提供完整的工作流：
# 1. 邮箱配置管理
# 2. 下载账单（信用卡/支付宝/微信）
# 3. 查看已下载账单
# 4. 解析账单并导出 Beancount
# 5. AI 配置管理
# 6. AI 智能处理 Beancount
```

### 运行测试
```bash
# 运行特定测试文件
python -m pytest utils/test_amount_masking.py -v
python -m pytest utils/test_clean_amount.py -v
```

## 架构设计

### 核心模块结构

```
FinanceMailParser/
├── business_rules.yaml          # 业务规则（系统规则，如账单识别关键词）
├── run.py                      # CLI 主入口
├── constants.py                # 全局常量（路径、配置）
├── data_source/                # 数据源模块
│   └── qq_email/              # QQ邮箱数据源
│       ├── parser.py          # IMAP 连接、邮件获取
│       ├── email_processor.py # 邮件内容处理
│       └── config.py          # 邮箱配置管理
├── statement_parsers/          # 账单解析器（策略模式）
│   ├── parse.py               # 解析器路由
│   ├── abc.py, ccb.py, cmb.py, ceb.py, icbc.py  # 各银行解析器
│   ├── alipay.py, wechat.py   # 数字支付解析器
│   └── __init__.py            # 时间过滤工具
├── models/                     # 数据模型
│   ├── txn.py                 # Transaction 和 DigitalPaymentTransaction
│   └── source.py              # TransactionSource 枚举
├── utils/                      # 工具模块
│   ├── beancount_writer.py    # Beancount 导出
│   ├── beancount_validator.py # Beancount 对账工具
│   ├── amount_masking.py      # 金额脱敏与恢复
│   ├── prompt_builder_v2.py   # AI Prompt 构建
│   └── account_extractor.py   # 账户提取
├── ai/                         # AI 模块
│   ├── config.py              # AIConfigManager（配置管理）
│   └── service.py             # AIService（litellm + tenacity）
├── ui/                         # Streamlit UI
│   ├── app.py                 # UI 主入口
│   └── pages/                 # 各功能页面
├── config/                     # 配置管理
│   ├── config_manager.py      # ConfigManager（通用配置）
│   ├── business_rules.py      # business_rules.yaml 加载与校验
│   └── secrets.py             # 加密/解密工具
└── outputs/                    # 输出目录
    ├── beancount/             # Beancount 文件
    └── mask_maps/             # 金额脱敏映射
```

### 数据流程

**1. 下载阶段**
- `run.py` → `QQEmailParser` (IMAP 连接)
- 按时间范围搜索邮件（信用卡）或获取最新邮件（支付宝/微信）
- 保存到 `emails/` 目录

**2. 解析阶段**
- `parse_statement_email()` 根据邮件主题识别银行类型
- 路由到对应解析器（BeautifulSoup 解析 HTML / pandas 解析 CSV）
- 返回 `Transaction` 对象列表

**3. 合并阶段**
- `merge_transaction_descriptions()` 匹配信用卡和数字支付交易
- 按日期、金额、卡号匹配，合并描述信息
- 去除重复交易

**4. 输出阶段**
- 导出为 Beancount 格式（`transactions_to_beancount()`）
- 输出到 `outputs/beancount/transactions_YYYYMMDD_YYYYMMDD.bean`

### 关键设计模式

**策略模式 - 账单解析器**
- 每个银行独立解析器模块（`abc.py`, `ccb.py`, `cmb.py` 等）
- 统一接口：`parse_xxx_statement(file_path, start_date, end_date) -> List[Transaction]`
- `parse.py` 作为路由器，根据邮件主题分发

**时间过滤机制**
- **下载时间**：按邮件发送时间过滤（IMAP 搜索）
- **解析时间**：按交易发生时间过滤（解析器内部）
- 使用 `should_skip_by_time()` 和 `TimeFilterCounter` 统一处理

**数据模型继承**
- `Transaction`: 基础交易类
- `DigitalPaymentTransaction`: 继承 Transaction，增加 `card_source` 字段

## 添加新银行支持

1. 在 `statement_parsers/` 创建 `bank_name.py`
2. 实现解析函数：
   ```python
   def parse_bank_name_statement(file_path: str,
                                  start_date: Optional[datetime] = None,
                                  end_date: Optional[datetime] = None) -> List[Transaction]:
       # 使用 BeautifulSoup 解析 HTML 或 pandas 解析 CSV
       # 返回 Transaction 对象列表
   ```
3. 在 `statement_parsers/parse.py` 的 `parse_statement_email()` 添加路由逻辑
4. 在 `business_rules.yaml` 的 `email_subject_keywords` 添加关键词（如需要）

## AI 智能处理模块

### 概述
AI 模块用于智能处理 Beancount 账单，自动填充支出账户、参考历史记账习惯。核心功能包括金额脱敏、AI 调用、金额恢复、对账验证。

### 核心组件

**AIConfigManager** (`ai/config.py`)
- 管理 AI 提供商配置（OpenAI、Gemini、Anthropic、Azure）
- 配置保存在 `config.yaml` 的 `ai` section（API Key 加密存储）
- 支持测试连接、CRUD 操作

**AIService** (`ai/service.py`)
- 封装 litellm 调用、重试逻辑（tenacity）
- 返回 `CallStats`（成功状态、耗时、重试次数、Token 统计）
- 可重试错误：Timeout、RateLimitError、ServiceUnavailableError

**金额脱敏** (`utils/amount_masking.py`)
- 可逆脱敏：使用唯一映射标记
- 脱敏映射保存在 `outputs/mask_maps/{run_id}.json`
- 100% 精准恢复原始金额

**对账工具** (`utils/beancount_validator.py`)
- 验证 AI 处理前后的 Beancount 文件
- 检查交易数量、金额、描述是否一致
- 防止 AI 篡改或遗漏数据

### 使用流程
1. 在「AI 配置」页面配置提供商和 API Key
2. 在「解析账单」页面导出 Beancount
3. 在「AI 处理」页面选择最新账单和历史参考文件
4. 预览脱敏后的 Prompt
5. 发送到 AI 处理
6. 对账检查
7. 恢复真实金额并下载

## 配置文件

### 配置边界（重要）

本项目将配置明确分为两类：

- **用户输入配置（可变、可能含敏感信息）**：存放在 `config.yaml`（阶段 4 也会把“用户偏好规则”写入这里）
- **系统规则 / 运行参数（不包含敏感信息）**：
  - 运行参数：统一写死在 `constants.py`（并提供校验脚本/提交前校验）
  - 业务系统规则：存放在 `business_rules.yaml`（例如账单邮件识别关键词）

说明：
- 即使你在 `config.yaml` 中手动加入 `network/parsing/ui` 等段落，当前代码也不会读取（这些曾是过渡方案，已废弃）。

### config.yaml（仅用户输入/敏感信息）

默认路径为项目根目录 `config.yaml`，也可通过环境变量 `FINANCEMAILPARSER_CONFIG_FILE` 覆盖。

结构示例：
```yaml
email:
  qq:
    email: "your@qq.com"
    auth_code: "ENC[v1|...]"  # 加密存储

ai:
  provider: "openai"           # openai/gemini/anthropic/azure
  model: "gpt-4"
  api_key: "ENC[v1|...]"       # 加密存储
  base_url: ""                 # 可选：自定义端点
  timeout: 600
  max_retries: 3
  retry_interval: 2
```

**加密机制**：
- 使用环境变量 `FINANCEMAILPARSER_MASTER_PASSWORD` 作为主密码
- 敏感字段（auth_code、api_key）加密后以 `ENC[v1|...]` 格式存储
- 遗忘主密码将无法解密，需删除 `config.yaml` 重新配置

### constants.py（运行参数 + 路径常量）

#### 运行参数（不可由用户配置）

位置：`constants.py`

目前包含（示例）：
- IMAP 默认服务器：`DEFAULT_IMAP_SERVER`
- 下载超时（秒）：`DEFAULT_DOWNLOAD_TIMEOUT_SECONDS`
- 编码回退列表：`FALLBACK_ENCODINGS`
- CSV 解析默认值：`ALIPAY_CSV_DEFAULTS`、`WECHAT_CSV_DEFAULTS`

校验方式：
```bash
python scripts/validate_runtime_constants.py
python scripts/validate_business_rules.py
```

（可选）提交前校验（本项目配置了 pre-commit hook；若 `pre-commit` 不在 PATH，可用虚拟环境命令）：
```bash
.venv/bin/pre-commit run -a
```

#### 路径常量（支持环境变量覆盖）

位置：`constants.py`

可通过以下环境变量覆盖默认路径：
- `FINANCEMAILPARSER_CONFIG_FILE`
- `FINANCEMAILPARSER_BUSINESS_RULES_FILE`
- `FINANCEMAILPARSER_EMAILS_DIR`
- `FINANCEMAILPARSER_BEANCOUNT_OUTPUT_DIR`
- `FINANCEMAILPARSER_MASK_MAP_DIR`
- `FINANCEMAILPARSER_TRANSACTIONS_CSV`

## 注意事项

1. **配置必需**：运行前需在 UI 或 `config.yaml` 配置 QQ 邮箱账号与授权码
2. **IMAP 服务**：确保 QQ 邮箱已开启 IMAP 服务
3. **时间概念区分**：
   - 下载时间：邮件发送时间（用于搜索邮件）
   - 解析时间：交易发生时间（用于过滤输出）
4. **HTML 解析**：银行账单 HTML 结构变化会导致解析失败，需更新对应解析器
5. **一次性下载链接**：微信账单下载链接只能使用一次，本地已存在时会跳过下载
6. **金额脱敏**：AI 处理时所有金额会被脱敏，确保隐私安全
