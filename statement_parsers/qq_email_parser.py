from pathlib import Path
from typing import List, Optional

from models.txn import Transaction
from statement_parsers.abc import parse_abc_statement
from statement_parsers.ccb import parse_ccb_statement
from statement_parsers.ceb import parse_ceb_statement
from statement_parsers.cmb import parse_cmb_statement
from utils.logger import setup_logger

logger = setup_logger(__name__)

def parse_statement_email(email_folder: Path) -> Optional[List[Transaction]]:
    """
    解析邮件中的信用卡账单
    
    Args:
        email_folder: 邮件保存的文件夹路径
        
    Returns:
        解析出的交易记录列表，如果解析失败返回None
    """
    try:
        # 查找HTML内容文件
        html_file = email_folder / 'content.html'
        if not html_file.exists():
            logger.warning(f"未找到HTML内容文件: {html_file}")
            return None
            
        # 读取元数据，确定是哪个银行的账单
        metadata_file = email_folder / 'metadata.json'
        if not metadata_file.exists():
            logger.warning(f"未找到元数据文件: {metadata_file}")
            return None
            
        # 根据邮件主题判断银行类型并调用相应的解析函数
        subject = metadata_file.read_text(encoding='utf-8').lower()
        
        if '建设银行' in subject or 'ccb' in subject:
            logger.info("解析建设银行账单")
            return parse_ccb_statement(str(html_file))
            
        elif '招商银行' in subject or 'cmb' in subject:
            logger.info("解析招商银行账单")
            return parse_cmb_statement(str(html_file))
            
        elif '光大银行' in subject or 'ceb' in subject:
            logger.info("解析光大银行账单")
            return parse_ceb_statement(str(html_file))
            
        elif '农业银行' in subject or 'abc' in subject:
            logger.info("解析农业银行账单")
            return parse_abc_statement(str(html_file))
            
        else:
            logger.warning(f"未知的银行账单类型: {subject}")
            return None
            
    except Exception as e:
        logger.error(f"解析账单时出错: {str(e)}", exc_info=True)
        return None 