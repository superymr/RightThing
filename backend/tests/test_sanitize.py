"""脱敏测试。

这一层的测试重点不是「能不能匹配上」，而是**两个容易做错的方向**：

1. **幂等** —— 已经打过码的文本再跑一次必须一字不变。否则同一条 JD 两次分析
   会得到内容不同、content_hash 不同的两条记录，去重与缓存全部失效；
2. **不误伤** —— 脱敏正则写宽一点就能「多抓」，但会把「3年以上经验」「Python 3.10」
   「微信小程序」这类正常 JD 文字改坏，直接污染抽取结果。所以样例 JD 必须**一字不改**。
"""

from __future__ import annotations

import pytest

from app.utils.sanitize import contains_pii, sanitize_text


class TestRedaction:
    def test_phone_keeps_prefix_and_suffix(self):
        result = sanitize_text("联系电话：13812345678，欢迎咨询")
        assert "13812345678" not in result.text
        assert "138****5678" in result.text
        assert result.hits["phone"] == 1

    def test_landline(self):
        result = sanitize_text("座机 0755-88886666 转 801")
        assert "88886666" not in result.text
        assert result.hits["landline"] == 1

    def test_email(self):
        result = sanitize_text("简历发送至 zhang.san@example.com 或私聊")
        assert "zhang.san" not in result.text
        assert result.text.endswith("或私聊")
        assert "z***@example.com" in result.text

    def test_id_card_fully_masked(self):
        result = sanitize_text("身份证号 110101199003071234 请勿外传")
        assert "110101199003071234" not in result.text
        assert "*" * 18 in result.text
        # 生日与地区都不能残留
        assert "19900307" not in result.text
        assert "110101" not in result.text

    def test_wechat_and_qq(self):
        result = sanitize_text("微信：hr_recruit2024  QQ: 12345678")
        assert "hr_recruit2024" not in result.text
        assert "12345678" not in result.text
        assert result.hits["im"] == 2

    def test_bank_card(self):
        result = sanitize_text("卡号 6222021234567890123 仅供核对")
        assert "6222021234567890123" not in result.text
        assert result.hits["bank_card"] == 1

    def test_multiple_occurrences_all_masked(self):
        result = sanitize_text("13800001111 或 13900002222 都可以")
        assert result.hits["phone"] == 2
        assert "13800001111" not in result.text
        assert "13900002222" not in result.text

    def test_id_card_not_partially_read_as_phone(self):
        """18 位身份证不能被截出 11 位当手机号打码 —— 那会留下半截真实数字。"""
        result = sanitize_text("110101199003071234")
        assert result.hits.get("phone", 0) == 0
        assert result.hits["id_card"] == 1


class TestIdempotent:
    """幂等是这个模块最重要的性质。"""

    SAMPLES = [
        "联系电话：13812345678，邮箱 zhang.san@example.com",
        "座机 0755-88886666，微信：hr_recruit2024",
        "身份证 110101199003071234，卡号 6222021234567890123",
        "QQ: 12345678",
    ]

    @pytest.mark.parametrize("sample", SAMPLES)
    def test_second_pass_changes_nothing(self, sample):
        once = sanitize_text(sample)
        twice = sanitize_text(once.text)
        assert twice.text == once.text
        assert twice.total == 0

    def test_text_without_pii_is_untouched(self):
        text = "熟悉 Python 3.10 与 C++，3年以上经验，薪资 15000-25000 元"
        result = sanitize_text(text)
        assert result.text == text
        assert not result.changed


class TestNoFalsePositives:
    """宁可漏（有测试兜底），也不要把正常 JD 文字改坏。"""

    TRICKY = [
        "3年以上SLAM相关研发经验",
        "熟悉 Python 3.10、C++17、MySQL 8.0",
        "薪资范围 15000-25000 元/月",
        "2024年毕业的应届生优先",
        "有微信小程序或企业微信开发经验者优先",
        "熟悉 CAN 总线与 EtherCAT 通信协议",
        "岗位编号 JR2024001234 请在邮件标题注明",
        "掌握 Linux 内核裁剪与驱动移植",
        "团队规模 30 人，成立于 2015 年",
    ]

    @pytest.mark.parametrize("text", TRICKY)
    def test_untouched(self, text):
        assert sanitize_text(text).text == text, f"误伤：{text}"


class TestSampleDataClean:
    """内置样例 JD 是「真实感数据」的基线：脱敏不应改动它一个字。

    这条测试比上面的逐条断言更有价值 —— 它覆盖了两个方向的 24 条完整 JD，
    任何过宽的正则都会在这里立刻暴露。
    """

    def test_samples_unchanged(self):
        from app.config import DEFAULT_SAMPLE_DIR
        from app.sources import SampleSource

        source = SampleSource(DEFAULT_SAMPLE_DIR)
        jobs = source.all_jobs()
        assert jobs, "样例数据缺失，测试失去意义"

        changed = []
        for job in jobs:
            if sanitize_text(job.raw_text).changed:
                changed.append(job.source_job_id)
        assert not changed, f"以下样例 JD 被误伤：{changed}"


class TestHelpers:
    def test_contains_pii(self):
        assert contains_pii("联系 13812345678")
        assert contains_pii("a@b.com")
        assert not contains_pii("熟悉 Python 与 ROS")
        assert not contains_pii("")

    def test_describe_is_human_readable_and_leaks_nothing(self):
        result = sanitize_text("邮箱 a@b.com，手机 13812345678")
        described = result.describe()
        assert "邮箱" in described and "手机号" in described
        # 摘要只能出现类别计数，不能回显被打码的内容
        assert "13812345678" not in described
        assert "a@b.com" not in described
