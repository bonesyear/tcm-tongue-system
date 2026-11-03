"""批次 03 可靠性：周报生成器的诊断性回归。

覆盖：
  - 合法 JSON 但非对象（数组/字符串/数值）→ 跳过 + stderr 警告，不崩（历史：sort 时 r.get 崩）
  - date 输入契约：数值/非法 date 在趋势图、week_id 上有显式行为（告警 + 占位符），不静默
  - week_id 占位符不得让不同坏 date 的周报静默覆盖同一文件
  - 中文「副本/备份/快照」命名的档案不参与同日竞争
"""
import json
import os
import re
import sys
from datetime import datetime

import pytest

import generate_weekly_report as g

RECORD_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "2026-06-25_analysis.json"
)


@pytest.fixture
def real_raw():
    with open(RECORD_PATH, encoding="utf-8") as f:
        return json.load(f)


def _write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


# ============================================================
# 合法 JSON 非 dict：跳过 + 可诊断
# ============================================================
class TestNonDictJson:
    def test_json_array_skipped_with_warning(self, tmp_path, monkeypatch, capsys):
        daily = tmp_path / "daily"
        daily.mkdir()
        (daily / "2026-10-20_analysis.json").write_text("[1, 2, 3]", encoding="utf-8")
        _write(daily / "2026-10-21_analysis.json", {"date": "2026-10-21"})
        monkeypatch.setattr(g, "RECORDS_DIR", str(daily))

        records = g.load_week_records(datetime(2026, 10, 21))
        assert [r["date"] for r in records] == ["2026-10-21"]
        err = capsys.readouterr().err
        assert "2026-10-20_analysis.json" in err
        assert "JSON" in err

    def test_json_string_skipped_with_warning(self, tmp_path, monkeypatch, capsys):
        daily = tmp_path / "daily"
        daily.mkdir()
        (daily / "2026-10-20_analysis.json").write_text('"只是字符串"', encoding="utf-8")
        monkeypatch.setattr(g, "RECORDS_DIR", str(daily))

        records = g.load_week_records(datetime(2026, 10, 20))
        assert records == []
        assert "JSON" in capsys.readouterr().err


# ============================================================
# date 输入契约
# ============================================================
class TestDateContract:
    def test_numeric_date_trend_chart_no_crash(self, real_raw, tmp_path, monkeypatch):
        # 数值 date（20260624）：趋势图标签按 str 归一，不崩
        rec = dict(real_raw)
        rec["date"] = 20260624
        rec2 = dict(real_raw)
        rec2["date"] = "2026-06-25"
        monkeypatch.setattr(g, "CHARTS_DIR", str(tmp_path))

        path = g.generate_trend_chart([rec, rec2])
        assert path is not None and os.path.exists(path)

    @pytest.mark.parametrize("bad_date", ["not-a-date", "2026-13-99", 20260624])
    def test_invalid_date_week_id_warns_not_silent(self, real_raw, bad_date, capsys):
        # 非法/非 YYYY-MM-DD 的 date：week_id 落占位符且必须打 stderr 警告
        rec = dict(real_raw)
        rec["date"] = bad_date
        data = g.generate_weekly_report_data([rec])
        assert data["week_id"] == "YYYY-W00"
        err = capsys.readouterr().err
        assert "YYYY-W00" in err and "week_id" in err

    def test_valid_date_no_warning(self, real_raw, capsys):
        data = g.generate_weekly_report_data([real_raw])
        assert data["week_id"] == "2026-06-25_2026-06-25"
        assert "week_id" not in capsys.readouterr().err

    def test_mixed_date_sorting_is_string_based(self, tmp_path, monkeypatch):
        # 排序契约：date 一律 str() 归一后按字典序升序，str/int 混排不崩
        daily = tmp_path / "daily"
        daily.mkdir()
        _write(daily / "2026-10-20_analysis.json", {"date": 20261020})
        _write(daily / "2026-10-21_analysis.json", {"date": "2026-10-21"})
        monkeypatch.setattr(g, "RECORDS_DIR", str(daily))
        records = g.load_week_records(datetime(2026, 10, 21))
        # 契约：str() 归一后按字典序升序（'-'(0x2D) < '1'(0x31)，连字符格式排前）。
        # 重点是不崩且顺序确定；混合格式的语义排序本就不是支持场景
        assert [str(r["date"]) for r in records] == ["2026-10-21", "20261020"]


# ============================================================
# week_id 占位符不得静默覆盖同名周报文件
# ============================================================
class TestPlaceholderWeekIdFileNaming:
    def test_bad_date_report_file_not_silent_overwrite(self, real_raw, tmp_path,
                                                       monkeypatch, capsys):
        daily = tmp_path / "daily"
        weekly = tmp_path / "weekly"
        charts = tmp_path / "charts"
        daily.mkdir()
        # main() 的目录创建契约由 ensure_data_dirs() 在真实入口完成；
        # 这里 monkeypatch 指到临时目录，故先自建
        weekly.mkdir()
        charts.mkdir()
        rec = dict(real_raw)
        rec["date"] = "not-a-date"
        # 文件名须匹配 {目标日}*analysis*.json 才会被选中；记录内部 date 才是坏的
        _write(daily / "2026-10-26_analysis.json", rec)
        monkeypatch.setattr(g, "RECORDS_DIR", str(daily))
        monkeypatch.setattr(g, "WEEKLY_DIR", str(weekly))
        monkeypatch.setattr(g, "CHARTS_DIR", str(charts))
        monkeypatch.setattr(sys, "argv", ["generate_weekly_report.py", "2026-10-26"])

        g.main()
        files = os.listdir(weekly)
        assert len(files) == 1
        assert files[0] != "YYYY-W00_report.json"
        assert files[0] == "YYYY-W00_not-a-date_report.json"
        assert "覆盖" in capsys.readouterr().err


# ============================================================
# 中文「副本/备份/快照」命名排除
# ============================================================
class TestChineseArchiveNames:
    def test_canonical_wins_over_chinese_copies(self, tmp_path, monkeypatch):
        daily = tmp_path / "daily"
        daily.mkdir()
        _write(daily / "2026-10-20_analysis副本.json", {"date": "2026-10-20"})
        _write(daily / "2026-10-20_analysis备份.json", {"date": "2026-10-20"})
        _write(daily / "2026-10-20_analysis快照.json", {"date": "2026-10-20"})
        _write(daily / "2026-10-20_analysis.json", {"date": "2026-10-20"})
        monkeypatch.setattr(g, "RECORDS_DIR", str(daily))
        assert g._select_daily_file("2026-10-20").endswith("2026-10-20_analysis.json")

    @pytest.mark.parametrize("suffix", ["副本", "备份", "快照"])
    def test_only_chinese_copy_available_returns_none(self, tmp_path, monkeypatch,
                                                      suffix):
        daily = tmp_path / "daily"
        daily.mkdir()
        _write(daily / f"2026-10-20_analysis{suffix}.json", {"date": "2026-10-20"})
        monkeypatch.setattr(g, "RECORDS_DIR", str(daily))
        assert g._select_daily_file("2026-10-20") is None

    def test_load_week_records_ignores_chinese_copies(self, tmp_path, monkeypatch):
        daily = tmp_path / "daily"
        daily.mkdir()
        _write(daily / "2026-10-20_analysis副本.json", {"date": "2026-10-20"})
        monkeypatch.setattr(g, "RECORDS_DIR", str(daily))
        records = g.load_week_records(datetime(2026, 10, 20))
        assert records == []
