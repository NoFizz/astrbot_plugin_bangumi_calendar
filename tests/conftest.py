"""pytest 公共配置：注入 AstrBot SDK 最小替身，保证测试完全 hermetic。

测试不依赖真实 AstrBot 运行时、不读真实配置、不发网络请求。
本文件在 pytest 收集任何测试模块之前执行：

1. 把插件父目录（core/data/plugins）加入 ``sys.path``，使测试以包路径
   ``import astrbot_plugin_bangumi_calendar.main`` 导入——后续拆分为多模块包后此路径不变；
2. 把 ``astrbot.api`` / ``astrbot.api.event`` / ``astrbot.api.star`` 的最小
   替身写入 ``sys.modules``，与 main.py 第 9-11 行的实际导入一一对应；
3. 提供 ``make_plugin`` fixture：用 ``object.__new__`` 绕过 ``__init__``，
   避免 ``asyncio.create_task(_daily_task())`` 与封面目录等副作用。
"""

import enum
import importlib
import sys
import types
from pathlib import Path

import pytest

# conftest 位于 <插件>/tests/conftest.py：
# parents[0]=tests, parents[1]=插件目录, parents[2]=plugins 目录。
PLUGINS_DIR = Path(__file__).resolve().parents[2]
if str(PLUGINS_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGINS_DIR))


class _NoopLogger:
    """no-op 日志替身：静默吞掉所有日志调用，避免污染测试输出。"""

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass


class AstrBotConfig:
    """AstrBot 配置替身：dict 包装，提供 ``.get(key, default)``。"""

    def __init__(self, data=None):
        """初始化配置。

        Args:
            data: 初始配置 dict，可选。
        """
        self._data = dict(data or {})

    def get(self, key, default=None):
        """读取配置项。

        Args:
            key: 配置键。
            default: 键缺失时的默认值。

        Returns:
            配置值或默认值。
        """
        return self._data.get(key, default)


class _AstrMessageEvent:
    """最小事件替身：提供 handler 用到的两个结果构造方法。"""

    def image_result(self, url):
        """构造图片消息结果。

        Args:
            url: 图片地址。

        Returns:
            原样返回 url 的占位结果。
        """
        return url

    def plain_result(self, text):
        """构造文本消息结果。

        Args:
            text: 文本内容。

        Returns:
            原样返回 text 的占位结果。
        """
        return text


class _MessageChain:
    """最小消息链替身：``url_image`` 以 classmethod 形式提供（main.py 按此调用）。"""

    @classmethod
    def url_image(cls, url, name=None):
        """占位方法：返回一个新实例。

        Args:
            url: 图片地址。
            name: 图片名，可选。

        Returns:
            _MessageChain: 新实例。
        """
        return cls()


class _Filter:
    """``filter`` 替身：装饰器均为恒等操作。

    ``command_group`` 会给被装饰函数挂上 ``command``，否则
    main.py 中 ``@bangumi_cn.command("今日")`` 的链式用法会导入失败。
    """

    class PermissionType(enum.Enum):
        """权限类型枚举（仅含插件用到的 ADMIN）。"""

        ADMIN = "admin"

    def command_group(self, name):
        """命令组装饰器：恒等返回，并为函数附加 ``command`` 方法。

        Args:
            name: 命令组名。

        Returns:
            callable: 恒等装饰器。
        """

        def _decorator(func):
            func.command = self.command
            return func

        return _decorator

    def command(self, name):
        """子命令装饰器：恒等返回。

        Args:
            name: 子命令名。

        Returns:
            callable: 恒等装饰器。
        """
        return lambda func: func

    def permission_type(self, perm):
        """权限装饰器：恒等返回。

        Args:
            perm: 权限值（如 ``PermissionType.ADMIN``）。

        Returns:
            callable: 恒等装饰器。
        """
        return lambda func: func


class _Context:
    """最小上下文替身。"""

    async def send_message(self, umo, message):
        """占位推送方法。

        Args:
            umo: 目标 UMO 字符串。
            message: 消息链。
        """


class _Star:
    """Star 基类替身：普通基类，仅保存 context。"""

    def __init__(self, context=None):
        """初始化。

        Args:
            context: 上下文实例，可选。
        """
        self.context = context


def _register(*args, **kwargs):
    """``@register(...)`` 替身：恒等装饰器，返回类本身。

    Args:
        *args: 注册元数据（插件名、作者、描述、版本）。
        **kwargs: 预留。

    Returns:
        callable: 接收插件类并原样返回的装饰器。
    """

    def _decorator(cls):
        return cls

    return _decorator


def _make_module(name, **attrs):
    """创建并注册一个 stub 模块。

    Args:
        name: 模块全名（如 ``astrbot.api``）。
        **attrs: 模块属性。

    Returns:
        types.ModuleType: 已写入 ``sys.modules`` 的模块对象。
    """
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


_make_module("astrbot")
_make_module("astrbot.api", AstrBotConfig=AstrBotConfig, logger=_NoopLogger())
_make_module(
    "astrbot.api.event",
    AstrMessageEvent=_AstrMessageEvent,
    MessageChain=_MessageChain,
    filter=_Filter(),
)
_make_module("astrbot.api.star", Context=_Context, Star=_Star, register=_register)

# 在 stub 注入完成之后才导入插件，确保 main.py 顶层 import 命中替身。
plugin_main = importlib.import_module("astrbot_plugin_bangumi_calendar.main")


@pytest.fixture
def make_plugin():
    """返回构造测试用插件实例的工厂。

    用 ``object.__new__`` 绕过 ``__init__``，从而不触发
    ``asyncio.create_task(_daily_task())``、封面目录创建等副作用。
    调用方可随后自由覆盖 config 之外的属性（如 ``html_render``）。
    """

    def _make(config=None, **overrides):
        """构造插件实例。

        Args:
            config: 初始配置 dict，可选。
            **overrides: 覆盖/追加的配置项。

        Returns:
            BangumiCalendarPlugin: 已设置 ``config`` 的实例。
        """
        data = dict(config or {})
        data.update(overrides)
        plugin = object.__new__(plugin_main.BangumiCalendarPlugin)
        plugin.config = AstrBotConfig(data)
        return plugin

    return _make
