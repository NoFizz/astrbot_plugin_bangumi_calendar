"""parser.select_tags 单元测试：来源/放送/题材三类 tag 的筛选规则。

规则（用户指定）：
- 按添加人数 count 降序筛选，最多 max_count 个（默认 5）；
- 第一位取来源类型（原创/漫画改/小说改/游戏改/动画改/影视改，含简写映射 漫改→漫画改）；
- 第二位取放送方式（TV/WEB/OVA/剧场版/动态漫画）；
- 第三位起取题材白名单，按 count 降序填满；
- 国家/地区与杂项 tag 一律排除；
- 来源/放送缺失时跳过对应位，不做二次排序。

数据来自实测 API（subject 326 攻殻機動隊 S.A.C. 2nd GIG 的 tags 前六）。
所有用例 hermetic：无网络、无 astrbot 依赖。
"""

import pytest

from astrbot_plugin_bangumi_calendar.parser import select_tags

# 实测 /v0/subjects/326 的 tags（name, count）：科幻2300、TV 1314、漫画改417、
# 战斗229、日本188、漫改132
_326_TAGS = [
    {"name": "科幻", "count": 2300},
    {"name": "TV", "count": 1314},
    {"name": "漫画改", "count": 417},
    {"name": "战斗", "count": 229},
    {"name": "日本", "count": 188},
    {"name": "漫改", "count": 132},
]


class TestSelectTagsRealCase:
    """实测数据端到端：326 用例与顺序契约。"""

    def test_326_real_case(self):
        """Given subject 326 实测 tags，When 筛选，Then 输出 漫画改 TV 科幻 战斗（日本被排除）。"""
        assert select_tags(_326_TAGS) == ["漫画改", "TV", "科幻", "战斗"]

    def test_highest_count_source_wins(self):
        """Given 多个来源 tag，When 筛选，Then 取 count 最大者。"""
        tags = [
            {"name": "小说改", "count": 10},
            {"name": "漫画改", "count": 417},
            {"name": "游戏改", "count": 30},
        ]
        assert select_tags(tags) == ["漫画改"]

    def test_order_is_source_then_airing_then_genres(self):
        """Given 题材 count 高于来源/放送，When 筛选，Then 仍按 来源→放送→题材 排位。"""
        tags = [
            {"name": "科幻", "count": 2300},
            {"name": "TV", "count": 1314},
            {"name": "漫画改", "count": 417},
        ]
        assert select_tags(tags) == ["漫画改", "TV", "科幻"]


class TestSelectTagsSource:
    """来源位：白名单集合匹配与简写归一化。"""

    def test_man_gai_alias_maps_to_comic(self):
        """Given 仅含简写「漫改」的来源 tag，When 筛选，Then 归一化为「漫画改」。"""
        tags = [{"name": "漫改", "count": 500}, {"name": "科幻", "count": 100}]
        assert select_tags(tags) == ["漫画改", "科幻"]

    def test_original_source(self):
        """Given 含「原创」tag，When 筛选，Then 来源位为「原创」。"""
        tags = [{"name": "原创", "count": 900}, {"name": "TV", "count": 800}]
        assert select_tags(tags) == ["原创", "TV"]

    def test_source_missing_skips_slot(self):
        """Given 无任何来源 tag，When 筛选，Then 首位为放送 tag。"""
        tags = [{"name": "TV", "count": 1314}, {"name": "科幻", "count": 2300}]
        assert select_tags(tags) == ["TV", "科幻"]

    def test_synonym_counts_merge(self):
        """Given 简写与全称同时存在，When 筛选，Then 归一化后同名合并计数。"""
        tags = [
            {"name": "漫改", "count": 300},
            {"name": "漫画改", "count": 400},
            {"name": "游戏改", "count": 600},
        ]
        assert select_tags(tags) == ["漫画改"]


class TestSelectTagsAiring:
    """放送位：五种放送方式严格匹配。"""

    @pytest.mark.parametrize("name", ["TV", "WEB", "OVA", "剧场版", "动态漫画"])
    def test_all_airing_kinds(self, name):
        """Given 放送方式 {name}，When 筛选，Then 放送位取该值。"""
        tags = [{"name": "原创", "count": 500}, {"name": name, "count": 400}]
        assert select_tags(tags)[1] == name

    def test_airing_missing_skips_slot(self):
        """Given 无放送 tag，When 筛选，Then 第二位为题材 tag。"""
        tags = [{"name": "漫画改", "count": 417}, {"name": "科幻", "count": 2300}]
        assert select_tags(tags) == ["漫画改", "科幻"]

    def test_non_airing_kind_skipped(self):
        """Given 放送相关但不在集合内（如 Movie），When 筛选，Then 跳过不放行。"""
        tags = [{"name": "漫画改", "count": 417}, {"name": "Movie", "count": 999}]
        assert select_tags(tags) == ["漫画改"]


class TestSelectTagsGenre:
    """题材位：白名单内按 count 降序填充，不超 max_count。"""

    def test_genres_fill_by_count_desc(self):
        """Given 多个题材 tag，When 筛选，Then 按 count 降序填充。"""
        tags = [
            {"name": "战斗", "count": 229},
            {"name": "恋爱", "count": 600},
            {"name": "日常", "count": 100},
            {"name": "悬疑", "count": 300},
        ]
        assert select_tags(tags) == ["恋爱", "悬疑", "战斗", "日常"]

    def test_truncates_to_max_count(self):
        """Given 超过 max_count 个题材，When 筛选，Then 截断为前 max_count 个。"""
        names = ["科幻", "喜剧", "百合", "校园", "惊悚", "后宫", "机战", "悬疑"]
        tags = [{"name": n, "count": 800 - i} for i, n in enumerate(names)]
        assert select_tags(tags) == names[:5]

    def test_custom_max_count(self):
        """Given max_count=2，When 筛选，Then 最多返回 2 个且保留排位顺序。"""
        tags = [
            {"name": "漫画改", "count": 417},
            {"name": "TV", "count": 1314},
            {"name": "科幻", "count": 2300},
        ]
        assert select_tags(tags, max_count=2) == ["漫画改", "TV"]


class TestSelectTagsExclusion:
    """排除规则：国家/地区与白名单外杂项一律不进入题材位。"""

    def test_country_tags_excluded(self):
        """Given 含国家 tag，When 筛选，Then 日本/国产/中国/美国等被排除。"""
        tags = [
            {"name": "原创", "count": 500},
            {"name": "TV", "count": 400},
            {"name": "日本", "count": 188},
            {"name": "国产", "count": 90},
            {"name": "中国", "count": 80},
            {"name": "美国", "count": 70},
            {"name": "科幻", "count": 2300},
        ]
        assert select_tags(tags) == ["原创", "TV", "科幻"]

    def test_misc_tags_skipped(self):
        """Given 人名/公司/年份/评价词等杂项 tag，When 筛选，Then 一律跳过不占位。"""
        tags = [
            {"name": "漫画改", "count": 417},
            {"name": "神作", "count": 9999},
            {"name": "2023", "count": 500},
            {"name": "SHAFT", "count": 300},
            {"name": "虚渊玄", "count": 200},
        ]
        assert select_tags(tags) == ["漫画改"]


class TestSelectTagsEdge:
    """边界：空输入、异常条目、max_count 边界。"""

    def test_empty_input_returns_empty(self):
        """Given 空列表，When 筛选，Then 返回空列表。"""
        assert select_tags([]) == []

    def test_none_input_returns_empty(self):
        """Given None 输入，When 筛选，Then 返回空列表。"""
        assert select_tags(None) == []

    def test_zero_max_count_returns_empty(self):
        """Given max_count=0，When 筛选，Then 返回空列表。"""
        assert select_tags([{"name": "漫画改", "count": 417}], max_count=0) == []

    def test_malformed_entries_skipped(self):
        """Given 条目缺 name/count 或类型异常，When 筛选，Then 跳过不崩溃。"""
        tags = [{"name": "TV", "count": "many"}, {"count": 100}, {"name": ""}, "junk", None]
        assert select_tags(tags) == []
