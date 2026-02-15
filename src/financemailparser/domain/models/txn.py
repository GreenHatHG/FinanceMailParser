from .source import TransactionSource


class Transaction:
    def __init__(
        self,
        source,
        date,
        description,
        amount,
        payee="",
        category="",
        account="",
        transfers="",
        check_num="",
        memo="",
        tags="",
    ):
        self.source = TransactionSource.from_str(source.strip())
        self.date = date.strip()
        self.description = description.strip()
        self.amount = float(str(amount).replace(" ", "").replace(",", ""))
        self.payee = payee.strip()
        self.category = category.strip()
        self.account = account.strip()
        self.transfers = transfers.strip()
        self.check_num = check_num.strip()
        self.memo = memo.strip()
        self.tags = tags.strip()

    def to_dict(self):
        return {
            "source": str(self.source),
            "date": self.date,
            "description": self.description,
            "amount": self.amount,
            "payee": self.payee,
            "category": self.category,
            "account": self.account,
            "transfers": self.transfers,
            "check_num": self.check_num,
            "memo": self.memo,
            "tags": self.tags,
        }


class DigitalPaymentTransaction(Transaction):
    def __init__(self, source, date, description, amount, payment_method="", **kwargs):
        super().__init__(source, date, description, amount, **kwargs)
        self.card_source = None  # 用于存储关联的信用卡信息
