class Transaction:
    def __init__(self, source, date, description, amount, payee="", category="", account="", transfers="", check_num="",
                 memo="", tags=""):
        self.source = source.strip()
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
        return self.get_write_row(date=self.date, category=self.category, amount=self.amount,
                                  description=self.description)

    def to_dict(self):
        return self.__dict__

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
