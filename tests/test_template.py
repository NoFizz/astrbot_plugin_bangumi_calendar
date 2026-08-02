"""HTML_TMPL 模板回归测试：字段契约、760px 宽度契约、三栏结构、Jinja2 注入转义。

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
        "index": 1,
        "score": 9.3,
        "doing": 12034,
        "air_date": "2023-09-29",
        "cover": "",
        "rank": None,
        "tags": [],
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

    def test_keeps_760px_width(self):
        """Given HTML_TMPL 源码，Then 保留 760px 视口与文档宽度契约。"""
        assert 'width=760' in HTML_TMPL
        assert 'width: 760px' in HTML_TMPL

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
        assert "{{ a.index | e }}" in HTML_TMPL
        assert "{{ a.rank | e }}" in HTML_TMPL
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

    def test_renders_index_numbers_in_order(self):
        """Given items 带递增 index，When 渲染，Then 序号区输出对应数字。"""
        html = _render([_item(index=1), _item(name="Kusuriya no Hitorigoto", name_cn="药屋少女的呢喃", index=2)])

        assert '<div class="index-num">1</div>' in html
        assert '<div class="index-num">2</div>' in html

    def test_renders_rank_value_when_present(self):
        """Given rank 有值，When 渲染，Then 标题右侧输出 Rank N 蓝色胶囊。"""
        html = _render([_item(rank=9565)])

        assert 'class="rank-badge"' in html
        assert "Rank 9565" in html
        assert "暂无排名" not in html

    @pytest.mark.parametrize("rank", [None, 0])
    def test_omits_rank_badge_when_missing(self, rank):
        """Given rank 缺失或为 0（未上榜），When 渲染，Then 不显示 rank 胶囊。"""
        html = _render([_item(rank=rank)])

        assert 'class="rank-badge"' not in html
        assert "Rank" not in html

    def test_three_column_structure(self):
        """Given 完整数据（有图/无图各一条），When 渲染，Then 封面/信息/序号区三栏齐全。"""
        html = _render([_item(cover="data:image/jpeg;base64,AAAA", rank=42), _item(index=2)])

        assert 'class="cover"' in html  # 左栏：封面（有图时 img.cover）
        assert 'class="cover-placeholder"' in html  # 左栏：无图占位
        assert 'class="info"' in html  # 中栏：番剧信息
        assert 'class="index-col"' in html  # 右栏：今日序号区
        assert 'class="rank-badge"' in html  # 中栏标题右侧含 rank 胶囊


class TestTagsRow:
    """tag 行：有 tags 渲染胶囊徽章（已筛选，模板直接渲染），空 tags 不渲染行。"""

    def test_renders_tag_chips_when_present(self):
        """Given item 带 tags，When 渲染，Then 输出 tags 行与对应胶囊徽章。"""
        html = _render([_item(tags=["漫画改", "TV", "科幻"])])

        assert '<div class="tags">' in html
        assert '<span class="tag">漫画改</span>' in html
        assert '<span class="tag">TV</span>' in html
        assert '<span class="tag">科幻</span>' in html

    def test_empty_tags_list_renders_no_row(self):
        """Given item tags 为空列表，When 渲染，Then 不输出 tags 行。"""
        html = _render([_item(tags=[])])

        assert 'class="tags"' not in html

    def test_missing_tags_key_renders_no_row(self):
        """Given item 缺 tags 键（旧数据兼容），When 渲染，Then 不输出 tags 行。"""
        item = _item()
        del item["tags"]
        html = _render([item])

        assert 'class="tags"' not in html

    def test_tag_value_is_escaped(self):
        """Given tag 含注入载荷，When 渲染，Then 被转义。"""
        html = _render([_item(tags=[_SCRIPT_NAME])])

        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert _SCRIPT_NAME not in html

    def test_source_has_tag_row_css_and_escape(self):
        """Given HTML_TMPL 源码，Then tag 插值带 | e 转义且 flex 换行/胶囊样式齐全。"""
        assert "{{ t | e }}" in HTML_TMPL
        assert "flex-wrap" in HTML_TMPL
        assert "gap: 6px" in HTML_TMPL
        assert "margin-top: 8px" in HTML_TMPL
        assert "999px" in HTML_TMPL
        assert "var(--accent-soft)" in HTML_TMPL


class TestIndexColumnBlue:
    """序号区淡蓝底 + 白色数字：背景 --index-bg（官方 Lb2）、数字 --index-num 白色。"""

    def test_index_col_uses_light_blue_background(self):
        """Given HTML_TMPL 源码，Then 序号区背景为淡蓝、数字为白色且变量已定义。"""
        assert "background: var(--index-bg);" in HTML_TMPL
        assert "color: var(--index-num);" in HTML_TMPL
        assert "--index-bg: #BFEDFA;" in HTML_TMPL
        assert "--index-num: #FFFFFF;" in HTML_TMPL

    def test_index_col_keeps_88px_width_and_centered(self):
        """Given HTML_TMPL 源码，Then 序号区保留 88px 定宽与垂直居中布局。"""
        assert "width: 88px" in HTML_TMPL
        assert "align-items: center" in HTML_TMPL
