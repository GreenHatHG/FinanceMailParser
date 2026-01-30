# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

FinanceMailParser 是一个金融账单邮件解析工具，用于自动化处理和解析来自QQ邮箱的金融账单。项目支持信用卡账单（多家银行）、支付宝账单和微信支付账单的解析，并将数据统一整理成标准格式。

## 核心命令

### 环境设置
```bash
# 安装依赖
pip install -r requirements.txt
```

### 下载账单
```bash
# 下载信用卡账单（按邮件发送时间）
python run.py download --type credit-card --start-date 2024-01-01 --end-date 2024-03-31

# 下载数字支付账单（支付宝和微信）
python run.py download --type digital-payment --alipay-pwd <密码> --wechat-pwd <密码>

# 默认下载信用卡账单
python run.py download --start-date 2024-01-01 --end-date 2024-03-31
```

### 解析账单
```bash
# 解析已下载的账单（按交易发生时间）
python run.py parse --start-date 2024-02-01 --end-date 2024-02-29

# 设置日志级别
python run.py parse --start-date 2024-02-01 --end-date 2024-02-29 --log-level DEBUG
```

## 架构设计

### 核心模块结构

```
FinanceMailParser/
├── run.py                      # 主入口，命令行接口
├── data_source/                # 数据源模块
│   └── qq_email/              # QQ邮箱数据源
│       ├── parser.py          # 邮件解析器（IMAP连接、邮件获取）
│       ├── email_processor.py # 邮件内容处理
│       ├── config.py          # QQ邮箱配置管理
│       ├── utils.py           # 工具函数
│       └── exceptions.py      # 自定义异常
├── statement_parsers/          # 账单解析器模块
│   ├── parse.py               # 解析器路由（根据银行类型分发）
│   ├── abc.py                 # 农业银行解析器
│   ├── ccb.py                 # 建设银行解析器
│   ├── cmb.py                 # 招商银行解析器
│   ├── ceb.py                 # 光大银行解析器
│   ├── icbc.py                # 工商银行解析器
│   ├── alipay.py              # 支付宝解析器
│   ├── wechat.py              # 微信支付解析器
│   └── __init__.py            # 通用工具（时间过滤、日期格式化）
├── models/                     # 数据模型
│   ├── txn.py                 # Transaction 和 DigitalPaymentTransaction 类
│   └── source.py              # TransactionSource 枚举
├── utils/                      # 工具模块
│   ├── csv_writer.py          # CSV 写入器
│   ├── logger.py              # 日志配置
│   ├── clean_amount.py        # 金额清洗
│   ├── filter_transactions.py # 交易过滤
│   ├── amount_masking.py      # 金额脱敏与恢复
│   ├── beancount_file_manager.py # Beancount 文件管理
│   ├── beancount_validator.py # Beancount 对账工具（2.7.4）
│   └── prompt_builder.py      # AI Prompt 构建
├── ai/                         # AI 模块（2.7.3）
│   ├── __init__.py            # 模块初始化
│   ├── config.py              # AIConfigManager - AI 配置管理
│   └── service.py             # AIService - AI 调用服务（litellm + tenacity）
├── ui/                         # Streamlit UI 模块
│   ├── app.py                 # 主入口
│   └── pages/                 # 页面
│       ├── email_config.py    # 邮箱配置管理
│       ├── download_bills.py  # 下载账单
│       ├── view_bills.py      # 查看账单
│       ├── parse_bills.py     # 解析账单
│       ├── ai_config.py       # AI 配置管理（2.7.3）
│       └── ai_process_beancount.py # AI 智能处理 Beancount（2.7.1-2.7.3）
├── config/                     # 配置模块
│   └── config_manager.py      # ConfigManager - 通用配置管理
├── qianji/                     # 钱迹相关功能
│   ├── qianji_to_beancount.py # 钱迹数据转 Beancount 格式
│   └── aggregate_expenses.py  # 支出聚合统计
└── outputs/                    # 输出目录
    ├── beancount/             # Beancount 文件输出
    └── mask_maps/             # 金额脱敏映射（敏感）
```

### 数据流程

1. **下载阶段** (`download` 命令)
   - `run.py` → `QQEmailParser` (data_source/qq_email/parser.py)
   - 通过 IMAP 连接 QQ 邮箱
   - 根据时间范围和类型搜索邮件
   - 保存邮件内容到 `emails/` 目录
   - 信用卡账单：保存 HTML 内容和元数据
   - 数字支付账单：下载并解压 ZIP 附件

2. **解析阶段** (`parse` 命令)
   - `run.py` → `parse_statement_email()` (statement_parsers/parse.py)
   - 根据邮件主题或文件夹名识别银行类型
   - 路由到对应的解析器（ccb.py, cmb.py, alipay.py 等）
   - 每个解析器使用 BeautifulSoup 解析 HTML 或 pandas 解析 CSV
   - 返回 `Transaction` 或 `DigitalPaymentTransaction` 对象列表

3. **合并阶段**
   - `merge_transaction_descriptions()` (run.py:248)
   - 匹配信用卡交易和数字支付交易（按日期、金额、卡号）
   - 合并描述信息（选择更详细的描述）
   - 去除重复的数字支付交易

4. **输出阶段**
   - `categorize_transaction()` (run.py:359) - 自动分类交易
   - `to_csv()` (run.py:377) - 写入 CSV 文件
   - 输出到 `transactions.csv`

### 关键设计模式

#### 1. 策略模式 - 账单解析器
每个银行的账单格式不同，使用独立的解析器模块：
- 所有解析器接受相同的参数：`(file_path, start_date, end_date)`
- 返回统一的 `List[Transaction]` 格式
- `parse.py` 作为路由器，根据邮件主题分发到对应解析器

#### 2. 数据模型继承
- `Transaction`: 基础交易类
- `DigitalPaymentTransaction`: 继承自 Transaction，增加 `card_source` 字段用于关联信用卡

#### 3. 时间过滤机制
- **下载时间范围**：按邮件发送时间过滤（IMAP 搜索）
- **解析时间范围**：按交易发生时间过滤（解析器内部）
- 使��� `should_skip_by_time()` 和 `TimeFilterCounter` 统一处理

## 添加新银行支持

1. 在 `statement_parsers/` 创建新文件（如 `bank_name.py`）
2. 实现解析函数：
   ```python
   def parse_bank_name_statement(file_path: str,
                                  start_date: Optional[datetime] = None,
                                  end_date: Optional[datetime] = None) -> List[Transaction]:
       # 使用 BeautifulSoup 解析 HTML 或 pandas 解析 CSV
       # 返回 Transaction 对象列表
   ```
3. 在 `statement_parsers/parse.py` 的 `parse_statement_email()` 添加路由逻辑
4. 在 `data_source/qq_email/parser.py` 的 `BILL_KEYWORDS` 添加关键词（如需要）

## 交易分类

交易自动分类基于关键词匹配（run.py:18-55）：
- `TRANSPORT_KEYWORDS`: 交通类交易
- `MEAL_KEYWORDS`: 餐饮类交易
- 默认分类：Todo

修改分类规则：编辑 `run.py` 中的关键词列表和 `categorize_transaction()` 函数。

## 数据存储

- **邮件存储**: `emails/` 目录
  - 信用卡账单：`emails/YYYYMMDD_邮件主题/`
  - 支付宝账单：`emails/alipay/`
  - 微信账单：`emails/wechat/`
- **解析输出**: `transactions.csv`（根目录）

## 注意事项

1. **配置必需**: 运行前需在 UI 或 `config.yaml` 配置 QQ 邮箱账号与授权码
2. **IMAP 服务**: 确保 QQ 邮箱已开启 IMAP 服务
3. **时间概念区分**:
   - 下载时间：邮件发送时间（用于搜索邮件）
   - 解析时间：交易发生时间（用于过滤输出）
4. **HTML 解析**: 银行账单 HTML 结构变化会导致解析失败，需要更新对应解析器
5. **日期格式**: 不同银行使用不同日期格式，解析器内部统一转换为 `YYYY-MM-DD`
6. **金额处理**: 使用 `clean_amount.py` 清洗金额字符串（去除空格、逗号等）

## Beancount 集成

项目包含钱迹数据转 Beancount 格式的功能（`qianji/qianji_to_beancount.py`），支持：
- CSV 格式转换
- 账户映射配置
- 多币种支持
- 子类别处理

## AI 智能处理模块（ui_plan.md 2.7）

### 概述

AI 模块用于智能处理 Beancount 账单，自动填充支出账户、参考历史记账习惯。核心功能包括金额脱敏、AI 调用、金额恢复。

### 模块架构

```
ai/
├── config.py          # AIConfigManager - AI 配置管理（CRUD、测试连接）
└── service.py         # AIService - AI 调用服务（litellm + tenacity 重试）
```

### 核心类

#### 1. AIConfigManager (`ai/config.py`)

**职责**：管理 AI 提供商配置（OpenAI、Gemini、Anthropic、Azure）

**配置结构**（保存在 `config.yaml` 的 `ai` section）：
```yaml
ai:
  provider: "openai"        # 提供商：openai/gemini/anthropic/azure/custom
  model: "gpt-4"            # 模型名称
  api_key: "ENC[v1|...]"    # API 密钥（加密存储，需 FINANCEMAILPARSER_MASTER_PASSWORD 解密）
  base_url: ""              # 可选：自定义端点
  timeout: 600              # 超时时间（秒）
  max_retries: 3            # 最大重试次数
  retry_interval: 2         # 重试间隔（秒）
```

**关键方法**：
- `load_config()` - 加载配置
- `save_config()` - 保存配置
- `delete_config()` - 删除配置
- `test_connection()` - 测试连接（发送简单 prompt 验证）
- `get_ai_config()` - 获取配置

**模型名称处理**：
- 自动为所有提供商添加前缀，确保 litellm 正确路由
- OpenAI: `openai/gpt-4`
- Gemini: `gemini/gemini-pro`
- Azure: `azure/gpt-4`
- Anthropic: `anthropic/claude-sonnet-4.5`

#### 2. AIService (`ai/service.py`)

**职责**：封装 litellm 调用、重试逻辑、Token 统计

**核心数据结构**：
```python
@dataclass
class CallStats:
    success: bool                    # 是否成功
    response: Optional[str]          # AI 返回内容
    total_time: float                # 总耗时（秒）
    retry_count: int                 # 实际重试次数
    error_message: Optional[str]     # 错误信息
    prompt_tokens: int               # 输入 Token 数
    completion_tokens: int           # 输出 Token 数
    total_tokens: int                # 总 Token 数
```

**关键方法**：
- `call_completion(prompt, system_prompt)` - 调用 AI 完成任务
- `_log_retry()` - 记录重试日志
- 返回 `CallStats` 对象，包含完整的调用统计

**重试策略**（使用 tenacity）：
- 可重试错误：`Timeout`、`RateLimitError`、`ServiceUnavailableError`、`APIConnectionError`
- 不可重试错误：`AuthenticationError`、`InvalidRequestError`
- 重试次数和间隔可配置

### UI 页面

#### 1. AI 配置页面 (`ui/pages/ai_config.py`)

**功能**：
- 当前配置状态展示
- 配置表单（提供商、模型、API Key、高级选项）
- 三个操作：保存配置、测试连接、删除配置
- API Key 掩码显示（安全性）

**参考设计**：`ui/pages/email_config.py`

#### 2. AI 处理 Beancount 页面 (`ui/pages/ai_process_beancount.py`)

**功能流程**：
1. 选择最新账单和历史参考文件
2. 金额脱敏（`AmountMasker`）
3. 构建 AI Prompt（`build_ai_prompt`）
4. 预览 Prompt（脱敏版本/真实版本）
5. 发送到 AI 处理
6. 展示调用统计（耗时、重试次数、Token 统计）
7. **对账检查**（`reconcile_beancount`）- 2.7.4
8. 恢复真实金额（`AmountMasker.unmask_text`）
9. 下载处理后的 Beancount 文件

**金额脱敏机制**（`utils/amount_masking.py`）：
- 可逆脱敏：使用唯一映射标记
- 脱敏映射保存在 `outputs/mask_maps/{run_id}.json`
- 支持页面刷新后恢复

### 使用流程

1. **配置 AI**：
   ```bash
   # 前往「AI 配置」页面填写配置
   ```

2. **测试连接**：
   - 在「AI 配置」页面点击「测试连接」
   - 验证配置是否正确

3. **处理账单**：
   - 前往「AI 处理 Beancount」页面
   - 选择最新账单和历史参考文件
   - 预览 Prompt
   - 点击「发送到 AI 处理」
   - 查看结果并恢复金额
   - 下载处理后的文件

### 关键技术点

1. **litellm 多提供商支持**：
   - 统一接口调用不同 AI 提供商
   - 显式前缀确保正确路由
   - 支持自定义端点（base_url）

2. **重试机制**：
   - 使用 tenacity 库实现
   - 可配置重试次数和间隔
   - 区分可重试和不可重试错误

3. **Token 统计**：
   - 从 litellm response 提取 usage 信息
   - 展示 prompt_tokens、completion_tokens、total_tokens

4. **金额脱敏与恢复**：
   - 确保 AI 不会看到真实金额
   - 可逆映射，100% 精准恢复
   - 支持持久化到本地

5. **错误处理**：
   - 详细的错误信息展示
   - 友好的错误提示
   - 完整的日志记录

### 配置文件位置

- **AI 配置**：`config.yaml` 的 `ai` section
- **脱敏映射**：`outputs/mask_maps/{run_id}.json`
- **Beancount 输出**：`outputs/beancount/`

### 依赖库

- `litellm` - 多提供商 LLM 调用
- `tenacity` - 重试机制
- `streamlit` - UI 框架
- `PyYAML` - 配置文件解析

