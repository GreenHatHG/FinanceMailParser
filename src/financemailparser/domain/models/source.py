from enum import Enum


class TransactionSource(Enum):
    """交易来源枚举"""

    CCB = "建设银行信用卡"
    CMB = "招商银行信用卡"
    CEB = "光大银行信用卡"
    ABC = "农业银行信用卡"
    ICBC = "工商银行信用卡"
    ALIPAY = "支付宝"
    WECHAT = "微信"

    @classmethod
    def from_str(cls, source: str) -> "TransactionSource":
        """从字符串获取枚举值"""
        source_map = {
            "建设银行信用卡": cls.CCB,
            "招商银行信用卡": cls.CMB,
            "光大银行信用卡": cls.CEB,
            "农业银行信用卡": cls.ABC,
            "工商银行信用卡": cls.ICBC,
            "支付宝": cls.ALIPAY,
            "微信": cls.WECHAT,
        }
        return source_map.get(source, source_map[source])

    def __str__(self) -> str:
        return self.value
