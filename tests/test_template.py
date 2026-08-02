"""HTML_TMPL 模板回归测试：字段契约、660px 宽度契约、Jinja2 注入转义。

测试用系统 Python 的 jinja2 直接渲染 ``card.HTML_TMPL``（显式关闭 autoescape，
验证模板自带 ``| e`` 转义而不依赖渲染环境的自动转义开关）。jinja2 仅测试环境依赖，
不加入插件 ``requirements.txt``。
"""

import pytest

from astrbot_plugin_bangumi_calendar.card import HTML_TMPL

jinja2 = pytest.importorskip("jinja2")

# 恶意名称样例：<script> 注入、属性逃逸注入（攻击 img/div 标签结构）
_SCRIPT_NAME = "<script>alert(1)</script>"
_ATTR_INJECT_NAME = "\"><img src=x onerror=alert(1)>"


def _render(items, **extra):
    """用 Jinja2（autoescape=False）渲染 HTML_TMPL，模拟 html_render 的模板环境。

    Args:
        items: 模板数据 items 列表。
        **extra: 覆盖 date/weekday/count 等顶层字段。

    Returns:
        str: 渲染后的 HTML 文本。
    """
    data = {
        "date": "2026-08-02",
        "weekday": "周日",
        "count": len(items),
        "items": items,
    }
    data.update(extra)
    return jinja2.Environment(autoescape=False).from_string(HTML_TMPL).render(**data)


def _item(**overrides):
    """构造一份模板契约内的最小合法番剧条目。

    Args:
        **overrides: 覆盖 name/name_cn/score/doing/air_date/cover 字段。

    Returns:
        dict: 完整字段的条目字典。
    """
    item = {
        "name": "Sousou no Frieren",
        "name_cn": "葬送的芙莉莲",
        "score": 9.3,
        "doing": 12034,
        "air_date": "2023-09-29",
        "cover": "",
    }
    item.update(overrides)
    return item


class TestEscaping:
    """模板注入转义：用户可控字段（番剧名等）渲染后必须被 HTML 转义。"""

    def test_script_in_name_is_escaped(self):
        """Given name 含 <script>，When 渲染，Then 输出含 &lt;script&gt; 且无原始标签。"""
        html = _render([_item(name=_SCRIPT_NAME, name_cn="中文名")])

        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert _SCRIPT_NAME not in html

    def test_script_in_name_cn_is_escaped(self):
        """Given 主标题 name_cn 含 <script>，When 渲染，Then 主标题被转义。"""
        html = _render([_item(name_cn=_SCRIPT_NAME)])

        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert _SCRIPT_NAME not in html

    def test_attr_injection_in_name_is_escaped(self):
        """Given name 含属性逃逸载荷，When 渲染，Then 引号与尖括号均被转义。"""
        html = _render([_item(name=_ATTR_INJECT_NAME, name_cn="中文名")])

        assert _ATTR_INJECT_NAME not in html
        # 引号实体会因 MarkupSafe 版本呈现为 &quot; 或 &#34;，只锁定尖括号转义结果
        assert "&lt;img src=x onerror=alert(1)&gt;" in html

    def test_attr_injection_in_name_cn_is_escaped(self):
        """Given name_cn 含属性逃逸载荷，When 渲染，Then 无法闭合外层标签。"""
        html = _render([_item(name_cn=_ATTR_INJECT_NAME)])

        assert _ATTR_INJECT_NAME not in html

    def test_air_date_injection_is_escaped(self):
        """Given air_date 含注入载荷，When 渲染，Then 被转义。"""
        payload = "<svg onload=alert(1)>"
        html = _render([_item(air_date=payload)])

        assert "&lt;svg onload=alert(1)&gt;" in html
        assert payload not in html

    def test_cover_src_injection_is_escaped(self):
        """Given cover 含属性逃逸载荷，When 渲染，Then img src 无法被闭合。"""
        payload = 'x" onerror="alert(1)'
        html = _render([_item(cover=payload)])

        assert 'onerror="alert(1)' not in html

    def test_score_and_doing_are_escaped(self):
        """Given score/doing 为文本型恶意值，When 渲染，Then 同样被转义。"""
        html = _render([_item(score=_SCRIPT_NAME, doing="1<2")])

        assert _SCRIPT_NAME not in html
        assert "1&lt;2" in html


class TestContract:
    """模板契约：字段、宽度、功能保留。"""

    def test_keeps_660px_width(self):
        """Given HTML_TMPL 源码，Then 保留 660px 视口与文档宽度契约。"""
        assert 'width=660' in HTML_TMPL
        assert 'width: 660px' in HTML_TMPL

    def test_renders_all_contract_fields(self):
        """Given 契约完整数据，When 渲染，Then 各字段均出现在输出中。"""
        html = _render(
            [
                _item(),
                _item(
                    name="Kusuriya no Hitorigoto",
                    name_cn="药屋少女的呢喃",
                    score=8.1,
                    doing=5200,
                    air_date="2023-10-21",
                ),
            ],
            date="2026-08-02",
            weekday="周日",
        )

        assert "2026-08-02" in html
        assert "周日" in html
        assert "葬送的芙莉莲" in html
        assert "Sousou no Frieren" in html
        assert "药屋少女的呢喃" in html
        assert "9.3" in html
        assert "12034" in html
        assert "2023-09-29" in html

    def test_escapes_every_interpolation_in_template_source(self):
        """Given HTML_TMPL 源码，Then 所有数据插值均带 | e 转义（含 or 优先级括号）。"""
        assert "{{ (a.name_cn or a.name) | e }}" in HTML_TMPL
        assert "{{ a.name | e }}" in HTML_TMPL
        assert "{{ a.cover | e }}" in HTML_TMPL
        assert "{{ a.air_date | e }}" in HTML_TMPL
        assert "{{ date | e }}" in HTML_TMPL
        assert "{{ weekday | e }}" in HTML_TMPL

    def test_keeps_cover_fallback_and_two_line_title(self):
        """Given 模板源码，Then 保留无图占位、双行标题、评分/在看/首播功能。"""
        assert "无图" in HTML_TMPL
        assert "onerror=" in HTML_TMPL
        assert "评分" in HTML_TMPL
        assert "在看" in HTML_TMPL
        assert "air_date" in HTML_TMPL
        assert "a.name_cn and a.name and a.name_cn != a.name" in HTML_TMPL
