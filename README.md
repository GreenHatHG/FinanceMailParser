# FinanceMailParser - 金融账单邮件解析工具

## 项目能力概览

FinanceMailParser 用于自动化处理金融账单邮件，当前支持：
- 信用卡账单（建设、招商、光大、农业、工商）
- 支付宝账单
- 微信支付账单

并提供：
- 账单下载、解析、去重、导出 Beancount
- AI 脱敏处理、账户补全与对账校验

## 使用说明

### 1) 环境准备

- Python `3.10+`
- 安装依赖（使用 uv）：如果你只想在脚本里调用解析逻辑，建议先安装核心依赖；只有在需要启动 UI 时再安装 `ui` extra。

```bash
uv sync --dev
# 如需启动 Streamlit UI：
uv sync --all-extras --dev
```

### 2) 设置主密码（用于敏感配置加密）

```bash
export FINANCEMAILPARSER_MASTER_PASSWORD='your_master_password'
```

说明：
- 该变量用于加密/解密 `config.yaml` 中的敏感字段（如邮箱授权码、AI API Key）。
- 需要在启动应用前设置。

### 3) 启动 Web 界面

```bash
uv run streamlit run ui/streamlit/app.py
```

## 技术说明

### 配置边界

- **用户输入配置**（可变、可能含敏感信息）：`config.yaml`
  - `email.qq.email`
  - `email.qq.auth_code`（加密）
  - `ai.provider/model/api_key`（`api_key` 加密）
  - `user_rules.*`
- **系统规则**：`business_rules.yaml`
- **路径与运行常量**：`src/financemailparser/shared/constants.py`

路径可通过环境变量覆盖：
- `FINANCEMAILPARSER_CONFIG_FILE`
- `FINANCEMAILPARSER_BUSINESS_RULES_FILE`
- `FINANCEMAILPARSER_EMAILS_DIR`
- `FINANCEMAILPARSER_BEANCOUNT_OUTPUT_DIR`
- `FINANCEMAILPARSER_MASK_MAP_DIR`
- `FINANCEMAILPARSER_TRANSACTIONS_CSV`

### 架构分层（目录结构与职责）

> 约定：本项目使用标准 `src layout`。可安装包名为 `financemailparser`，源码位于 `src/financemailparser/`。

```text
FinanceMailParser/
├── pyproject.toml
├── business_rules.yaml
├── config.yaml
├── ui/                              # 仓库级 UI（Streamlit 应用入口）
│   └── streamlit/
├── scripts/                         # 校验与开发脚本
├── tests/                           # 单元测试
│   └── shared/                      # shared 相关测试
├── emails/                          # 邮件落盘缓存（解析输入）
├── outputs/                         # 导出产物（输出）
└── src/financemailparser/           # 包源码（分层）
    ├── application/                 # 应用流程层（把功能串成流程）
    │   ├── billing/                 # 账单流程：下载/解析/导出
    │   ├── ai/                      # AI 流程：构建 Prompt / 调用 / 回写
    │   ├── settings/                # 配置流程：读取/保存/校验（给 UI 用）
    │   └── common/                  # 流程层公共代码
    ├── domain/                      # 核心模型与规则（尽量不做 IO）
    │   ├── models/                  # 领域模型
    │   └── services/                # 领域服务（纯逻辑能力）
    ├── infrastructure/              # 具体实现（IO/第三方/解析/落盘）
    │   ├── data_source/             # 邮箱等外部数据源（拉取/解析原始数据）
    │   ├── repositories/            # 本地仓储读写适配器（filesystem 等）
    │   ├── statement_parsers/       # 账单解析器
    │   │   ├── banks/               # 银行账单解析器
    │   │   └── digital_wallets/     # 支付宝/微信解析器
    │   ├── beancount/               # Beancount 写入/校验
    │   ├── exports/                 # 导出实现（CSV 等）
    │   ├── config/                  # 配置读取/加密
    │   └── ai/                      # AI provider/调用
    ├── integrations/                # 外部集成
    │   └── qianji/                  # 钱迹转换
    └── shared/                      # 跨层通用组件
```

目录职责说明（与上面目录树一一对应）：

仓库根目录（运行时文件与工程文件）：
- `pyproject.toml`：项目元信息与依赖定义（使用 uv 管理）；其中 `ui` extra 用于隔离前端依赖（`streamlit`）。
- `business_rules.yaml`：系统内置规则（例如账单邮件识别关键词、银行别名规则）。
- `config.yaml`：用户输入配置（可能包含加密字段，如邮箱授权码、AI API Key）。
- `ui/`：仓库级 UI（Streamlit 应用入口，不参与核心包 `.whl` 分发），只调用核心包暴露的流程。
- `emails/`：从邮箱下载/落盘的原始邮件内容（解析输入）。可视为缓存目录，必要时可清空重下。
- `outputs/`：导出产物（例如 `outputs/beancount/`）。
- `scripts/`：校验与开发脚本（pre-commit 会调用其中的校验脚本）。
- `tests/`：单元测试（使用 `pytest`）。

包目录（`src/financemailparser/`，按“分层依赖”组织）：
- `application/`：应用流程层（把“下载账单 / 解析导出 / AI 处理”等动作组织成可复用流程）。它会调用 `domain` 的纯逻辑、以及 `infrastructure` 的具体实现。
- `domain/`：核心模型与规则（尽量不做 IO，不依赖其他内部层），例如交易/来源枚举、以及“银行别名识别”这类纯逻辑。
  - `domain/models/`：领域模型（如 `Transaction`、`TransactionSource`）。
  - `domain/services/`：领域服务（纯逻辑能力，例如从邮件标题识别银行代码）。
- `infrastructure/`：具体实现（读写文件/调用第三方/解析 HTML/CSV/加解密等）。不依赖 `application`，也不关心 UI 入口在哪里。
  - `infrastructure/statement_parsers/`：账单解析器（银行/支付宝/微信），把输入文件解析为统一的 `Transaction`。
  - `infrastructure/data_source/`：数据源（当前为 QQ 邮箱）。
  - `infrastructure/repositories/`：仓储适配器（当前为本地 emails/ 目录的扫描与读取）。
  - `infrastructure/config/`：配置读取、校验、密钥加解密。
  - `infrastructure/ai/`：AI provider 与调用封装。
  - `infrastructure/beancount/`：Beancount 写入、解析与校验。
- `integrations/`：对外集成（例如 `qianji/` 钱迹相关转换）。
- `shared/`：跨层共享的通用组件（常量、脱敏、日期处理、轻量工具函数等），不依赖 `application/infrastructure/integrations`。

分层依赖方向：
- `ui/streamlit` → `application` → (`infrastructure` / `domain` / `shared`)
- UI 不直接依赖 `infrastructure`（UI 不碰“邮箱/解析/落盘”细节）
- `infrastructure` 不依赖 `application`（也不依赖仓库级 UI 入口）
- `domain` 不依赖其他内部层（只放纯逻辑）
- `shared` 不依赖 `application`、`infrastructure`、`integrations`

### 核心数据流程

1. **下载阶段**
   - `application/billing/download_credit_card.py`
   - `application/billing/download_digital.py`
   - 通过 `infrastructure/data_source/qq_email/parser.py` 获取邮件并落盘 `emails/`
2. **解析阶段**
   - `infrastructure/statement_parsers/parse.py::parse_statement_email()`
   - 按主题路由到银行/支付宝/微信解析器
3. **合并与规则处理**
   - `application/billing/parse_export.py`
   - `application/billing/transactions_postprocess.py`
4. **导出阶段**
   - `infrastructure/beancount/writer.py::transactions_to_beancount()`
   - 输出到 `outputs/beancount/`

### AI 处理核心组件

- `infrastructure/ai/config.py`：AI 配置管理
- `infrastructure/ai/service.py`：AI 调用与重试
- `application/ai/process_beancount.py`：AI 流程编排
- `shared/amount_masking.py`：金额可逆脱敏
- `infrastructure/beancount/validator.py`：结果对账校验

### 扩展：添加新银行解析器

1. 在 `financemailparser/infrastructure/statement_parsers/` 新增解析器文件（如 `bank_xxx.py`）
2. 实现统一接口 `parse_bank_xxx_statement(...) -> List[Transaction]`
3. 在 `infrastructure/statement_parsers/parse.py` 注册路由
4. 视需要更新 `business_rules.yaml` 关键词
