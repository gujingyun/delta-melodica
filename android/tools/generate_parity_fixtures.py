"""用桌面解析器生成自编谱基准；不读取个人曲库或访问网络。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from music import parse_jianpu_space

samples = [
    "0 |:1 2:|3 0", "|:1 |:2 3:|4:|5", "|:1:|:2:|",
    "1 2:|3 4:|5", "|:1 2[1 3:|[2 4|]5", "1 2[1 3:|[2 4",
    "|:1 |:2[1 3:|[2 4 5:|6", "|123|234||1|]",
    '|:1 /key(D4)2\nbpm60\n3:|4\nL:甲"(+1key)乙"丙丁',
    "|:1[1 /key(D4)2\nbpm60\n3:|[2 4",
    '1 2/key(D4)1 2\nL:甲"(+1key)乙"丙丁',
    "1_~|1.\nbpm60\n~1 0 (2_2) 3 3",
    "(1 2 2 0 3) 4", '((1 1) 2) 3 4\nL:甲乙丙"(+1key)丁"戊',
    "/key(A3)\nbpm108\n1_2_3-|1\nL:甲乙丙丁",
    "1\nC Em7 G7\n2", "1abc 2", "１_２，３",
    "1 0 - 2", "bpm300\n1=2_3..4--", "|:1~1 (2 3)[1 4:|[2 /key(D4)5 0",
    "|:1", "|::|", "|: /key(D4):|", "|:1[1:|[2 2", "|:1[1 2:|", "[2 1",
    "|:1[1 2:|[2", "|:1[1 2[1 3:|[2 4", "1~", "~1", "1~~1", "1~2", "1~0",
    "1~1/key(D4)~1", "(1", "1)", "()", "(0 1)", "(1 0)", "(1 0 1)",
    "|:(1:|2)", "(1|:2):|", "|:- 1:|", "0|:- 1:|", "1 D.C.", "1 /tuplet(3)234",
]
fixtures = []
for sample in samples:
    for mode in ("score", "source"):
        text = "/key(C4)\nbpm120\n" + sample
        item = {"text": text, "mode": mode}
        try:
            trace = []
            score, _ = parse_jianpu_space(text, "跨端基准", mode=mode, trace=trace)
            item["duration"] = round(score.duration * 1000)
            item["notes"] = [[round(n.start * 1000), round(n.end * 1000), n.pitch, n.legato] for n in score.notes]
            item["trace"] = [[a, b, round(c * 1000), round(d * 1000)] for a, b, c, d in trace]
        except ValueError:
            item["error"] = True
        fixtures.append(item)
target = Path(__file__).resolve().parents[1] / "app/src/test/resources/desktop-jianpu.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(fixtures, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"已生成 {len(fixtures)} 个跨端规则基准")
