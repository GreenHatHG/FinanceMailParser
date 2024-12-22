from .source import TransactionSource

class Transaction:
    def __init__(self, source, date, description, amount, payee="", category="", account="", transfers="", check_num="",
                 memo="", tags=""):
        self.source = TransactionSource.from_str(source.strip())
        self.date = date.strip()
        self.description = description.strip()
        self.amount = float(str(amount).replace(' ', '').replace(',', ''))
        self.payee = payee.strip()
        self.category = category.strip()
        self.account = account.strip()
        self.transfers = transfers.strip()
        self.check_num = check_num.strip()
        self.memo = memo.strip()
        self.tags = tags.strip()

    def writer_to_dict(self):
        """转换为写入CSV的格式"""
        return {
            '时间': self.date,
            '分类': self.category,
            '类型': '支出',
            '金额': self.amount,
            '备注': f"{str(self.source)}: {self.description}"
        }

    def to_dict(self):
        return {
            'source': str(self.source),
            'date': self.date,
            'description': self.description,
            'amount': self.amount,
            'payee': self.payee,
            'category': self.category,
            'account': self.account,
            'transfers': self.transfers,
            'check_num': self.check_num,
            'memo': self.memo,
            'tags': self.tags,
        }

    @staticmethod
    def get_write_row(date='', category='', amount=float(), description=''):
        return {
            '时间': date,
            '分类': category,
            '类型': '支出',
            '金额': amount,
            '备注': description
        }

    @staticmethod
    def get_fieldnames():
        return Transaction.get_write_row().keys()


class DigitalPaymentTransaction(Transaction):
    def __init__(self, source, date, description, amount, payment_method="", **kwargs):
        super().__init__(source, date, description, amount, **kwargs)
        self.card_source = None  # 用于存储关联的信用卡信息

