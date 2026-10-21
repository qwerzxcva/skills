# -*- coding: utf-8 -*-
import sys, os, json, re
sys.path.insert(0, r"C:\Users\Administrator\.workbuddy\skills\chanlun-multi-dim-analysis")
os.chdir(r"C:\Users\Administrator\.workbuddy\skills\chanlun-multi-dim-analysis")
from run_analysis import ChanlunAnalyzer

def load_rows(path):
    with open(path, 'r', encoding='utf-8') as f:
        txt = f.read()
    # 去掉 JSON 前的说明行
    start = txt.index('{')
    data = json.loads(txt[start:])
    return data['Rows']

jobs = [
    ("09988", "阿里巴巴-W", sys.argv[1]),
    ("00700", "腾讯控股",   sys.argv[2]),
]
for code, name, path in jobs:
    rows = load_rows(path)
    az = ChanlunAnalyzer(code, name)
    files = az.run_from_tdx_rows(rows)
    print(f"{code} {name} -> {files}")
