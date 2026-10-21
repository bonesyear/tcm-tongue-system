"""web 层切片 2 测试：记录列表 + 单日详情（只读）。

数据源指向 tmp_path 的 records 目录，不碰真实数据。
Flask 未装时整模块跳过（web/requirements.txt 独立声明）。
"""
import os
import sys

import pytest

pytest.importorskip("flask")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "web"))

from app import create_app  # noqa: E402

FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "2026-06-25_analysis.json")


@pytest.fixture
def data_root(tmp_path):
    d = tmp_path / "data"
    (d / "records" / "daily").mkdir(parents=True)
    (d / "records" / "photos").mkdir(parents=True)
    return str(d)


@pytest.fixture
def client(tmp_path, data_root, monkeypatch):
    for k in ("VISION_API_KEY", "WEB_ADMIN_TOKEN", "WEB_HOST"):
        monkeypatch.delenv(k, raising=False)
    app = create_app(env_file=str(tmp_path / ".env"), data_root=data_root)
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/welcome")  # 完成启动声明确认
    return c


@pytest.fixture
def demo_client(client):
    """已载入合成示例记录的 client。"""
    client.post("/demo")
    return client


def test_empty_library_shows_demo_banner(client):
    html = client.get("/").get_data(as_text=True)
    assert "载入示例数据" in html
    assert "暂无记录" in html


def test_load_demo_creates_record(demo_client, data_root):
    assert os.path.exists(os.path.join(
        data_root, "records", "daily", "2026-06-25_analysis.json"))
    html = demo_client.get("/").get_data(as_text=True)
    assert "06 / 25" in html  # 近七日行
    assert "载入示例数据" not in html


def test_record_detail_renders_engine_scores(demo_client):
    """详情页数字来自真实评分引擎（fixture 合成记录：总分 28.0）。"""
    resp = demo_client.get("/record/2026-06-25")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "舌诊" in html and "头面诊" in html
    assert "28.0 / 60" in html           # 六维之和 7+7+3+3+6+2（max 口径 v1.7.21）
    assert "均未触发" in html              # danger_flags 未触发横幅
    assert "六经归属" in html              # 辨证报告卡：结构化结论仍在
    assert "示例方" not in html            # 方剂块已移出第一张卡（只留完整报告）
    assert ">起居情志<" not in html        # 老记录无 lifestyle 字段：不显示、不回写伪造
    assert "参考项" in html                # 点刺/掌温降级字段
    assert "偏胖大" in html                # 观察值原文


def test_record_detail_unknown_date_404(demo_client):
    assert demo_client.get("/record/2026-01-01").status_code == 404
    assert demo_client.get("/record/not-a-date").status_code == 404


def test_calendar_marks_record_days(demo_client):
    html = demo_client.get("/?m=2026-06").get_data(as_text=True)
    assert "2026 年 6 月" in html
    assert 'href="/record/2026-06-25"' in html  # 有记录的日子可点
    assert "28.0" in html                        # 日历格总偏离度


def test_index_keeps_only_seven_recent_rows(demo_client, data_root):
    import shutil
    daily = os.path.join(data_root, "records", "daily")
    for i in range(10, 20):  # 再造 10 天 → 共 11 天
        shutil.copyfile(FIXTURE, os.path.join(
            daily, f"2026-06-{i:02d}_analysis.json"))
    html = demo_client.get("/").get_data(as_text=True)
    assert html.count('class="rec-row"') == 7  # 近七日只展示最近 7 条


def test_uncovered_dim_does_not_count_as_zero(demo_client, data_root):
    """未覆盖维度显示「未覆盖」，不计入总分（与 0 分正常严格区分）。"""
    import json
    daily = os.path.join(data_root, "records", "daily")
    with open(FIXTURE, encoding="utf-8") as f:
        raw = json.load(f)
    del raw["observations"]["skin"]  # 拿掉皮肤维度
    with open(os.path.join(daily, "2026-06-26_analysis.json"), "w",
              encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    html = demo_client.get("/record/2026-06-26").get_data(as_text=True)
    assert "未覆盖" in html
    assert "26.0 / 60" in html  # 28.0 - 皮肤 2.0


def test_review_badges_shown(demo_client):
    """待复核标记：齿痕/腻腐/厚薄/面色/黄染/舌下络脉等字段应有视觉标记（P1）。
    2026-10-20 起机制改为：行加 review 类（淡黄底）+ 字段名后圆点（title 述原因）。"""
    html = demo_client.get("/record/2026-06-25").get_data(as_text=True)
    assert 'class="field-row review"' in html
    assert html.count('class="field-row review"') >= 3  # fixture 中齿痕/厚薄/腻腐/面色/络脉迂曲均有值
    assert 'class="rv" title=' in html  # 圆点带复核原因 tooltip
