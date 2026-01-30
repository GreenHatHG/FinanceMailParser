"""
配置管理器模块

负责项目配置的 CRUD 操作，支持分层配置结构
"""

import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any

import yaml

from constants import CONFIG_FILE

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    配置管理器

    支持分层配置结构，方便扩展多种配置类型
    配置文件存储在项目根目录的 config.yaml 中

    配置文件结构示例：
    ```yaml
    email:
      qq:
        email: xxx@qq.com
        auth_code: xxx
      gmail:  # 未来可扩展
        email: xxx@gmail.com
        password: xxx
    database:  # 未来可扩展
      host: localhost
      port: 3306
    ```
    """

    def __init__(self, config_path: Optional[Path] = None):
        """
        初始化配置管理器

        Args:
            config_path: 配置文件路径，默认为项目根目录的 config.yaml
        """
        if config_path is None:
            # 使用全局常量定义的配置文件路径
            self.config_path = CONFIG_FILE
        else:
            self.config_path = config_path

    # ==================== 通用配置方法 ====================

    def _load_all_config(self) -> Dict[str, Any]:
        """
        加载完整的配置文件

        Returns:
            完整的配置字典，如果文件不存在返回空字典

        Raises:
            yaml.YAMLError: YAML 文件格式错误
        """
        if not self.config_path.exists():
            logger.debug(f"配置文件不存在: {self.config_path}")
            return {}

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)

            # 允许空配置（首次使用时 config.yaml 可能为空或为 {}）
            if config_data is None:
                return {}

            if not isinstance(config_data, dict):
                logger.warning("配置文件格式错误：不是有效的字典")
                return {}

            return config_data

        except yaml.YAMLError as e:
            logger.error(f"YAML 文件格式错误: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"加载配置失败: {str(e)}")
            return {}

    def _save_all_config(self, config_data: Dict[str, Any]) -> None:
        """
        保存完整的配置文件

        Args:
            config_data: 完整的配置字典

        Raises:
            Exception: 保存失败
        """
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)
            # Best-effort: restrict config file permissions (may not work on all platforms/filesystems).
            try:
                os.chmod(self.config_path, 0o600)
            except Exception as e:
                logger.debug(f"无法设置配置文件权限为 600: {str(e)}")
            logger.info(f"配置已保存到 {self.config_path}")
        except Exception as e:
            logger.error(f"保存配置失败: {str(e)}")
            raise

    def get_section(self, section: str) -> Optional[Dict[str, Any]]:
        """
        获取配置的某个节（section）

        Args:
            section: 配置节名称，如 'email', 'database'

        Returns:
            配置节的字典，如果不存在返回 None
        """
        try:
            config = self._load_all_config()
            return config.get(section)
        except Exception as e:
            logger.error(f"获取配置节 {section} 失败: {str(e)}")
            return None

    def set_section(self, section: str, data: Dict[str, Any]) -> None:
        """
        设置配置的某个节（section）

        Args:
            section: 配置节名称，如 'email', 'database'
            data: 配置节的数据字典

        Raises:
            Exception: 保存失败
        """
        config = self._load_all_config()
        config[section] = data
        self._save_all_config(config)
        logger.info(f"配置节 {section} 已更新")

    def get_value(self, section: str, key: str, default: Any = None) -> Any:
        """
        获取配置的某个值

        Args:
            section: 配置节名称，如 'email'
            key: 配置键名，如 'qq'
            default: 默认值

        Returns:
            配置值，如果不存在返回 default
        """
        section_data = self.get_section(section)
        if section_data is None:
            return default
        return section_data.get(key, default)

    def set_value(self, section: str, key: str, value: Any) -> None:
        """
        设置配置的某个值

        Args:
            section: 配置节名称，如 'email'
            key: 配置键名，如 'qq'
            value: 配置值

        Raises:
            Exception: 保存失败
        """
        config = self._load_all_config()

        # 确保 section 存在
        if section not in config:
            config[section] = {}

        # 设置值
        config[section][key] = value

        self._save_all_config(config)
        logger.info(f"配置 {section}.{key} 已更新")

    def delete_section(self, section: str) -> bool:
        """
        删除配置的某个节

        Args:
            section: 配置节名称

        Returns:
            是否删除成功
        """
        try:
            config = self._load_all_config()

            if section not in config:
                logger.warning(f"配置节 {section} 不存在")
                return True

            del config[section]
            self._save_all_config(config)
            logger.info(f"配置节 {section} 已删除")
            return True

        except Exception as e:
            logger.error(f"删除配置节 {section} 失败: {str(e)}")
            return False

    def config_exists(self) -> bool:
        """
        检查配置文件是否存在

        Returns:
            配置文件是否存在
        """
        return self.config_path.exists()

    def delete_value(self, section: str, key: str) -> bool:
        """
        删除配置中的某个键值（支持把空 section 一并清理掉）

        Args:
            section: 配置节名称，如 'email'
            key: 配置键名，如 'qq'

        Returns:
            是否删除成功
        """
        try:
            config = self._load_all_config()

            if section not in config or not isinstance(config.get(section), dict) or key not in config[section]:
                logger.warning(f"配置 {section}.{key} 不存在")
                return True

            del config[section][key]

            if not config[section]:
                del config[section]

            self._save_all_config(config)
            logger.info(f"配置 {section}.{key} 已删除")
            return True

        except Exception as e:
            logger.error(f"删除配置 {section}.{key} 失败: {str(e)}")
            return False
