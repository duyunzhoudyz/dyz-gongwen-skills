"""在真实引擎入口记录全部登记项，检查整个 JSON 报告与屏幕输出。"""
import json
from unittest.mock import patch


def check_masked_outputs(names_module, run):
    registered = set()
    add = names_module.NameTable.add

    def record(table, name):
        registered.add(name)
        return add(table, name)

    with patch.object(names_module.NameTable, "add", record):
        report, screen = run()
    outputs = (json.dumps(report, ensure_ascii=False), screen)
    leaked = sorted(name for name in registered if any(name in output for output in outputs))
    if leaked:
        raise AssertionError(f"已登记姓名在输出中泄露：{leaked}")
    return report, screen
