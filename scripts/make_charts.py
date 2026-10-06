"""Draw the README chart from the threshold sweep in reports/eval.md.
Needs matplotlib (pip install matplotlib); nothing else in the project depends on it.

    python scripts/make_charts.py
"""
import json
import re
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
BLUE, AQUA, RED, GRAY, INK, MUTED = "#2a78d6", "#1baf7a", "#e34948", "#8a8984", "#0b0b0b", "#52514e"

plt.rcParams.update({
    "font.size": 11, "axes.edgecolor": "#d6d5d0", "axes.labelcolor": MUTED,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": "#ecebe7",
    "axes.axisbelow": True, "figure.facecolor": "white", "axes.titleweight": "bold",
    "axes.titlecolor": INK,
})

report = (ROOT / "reports" / "eval.md").read_text(encoding="utf-8")
rows = [(float(t), float(a) / 100, float(k) / 100, int(w)) for t, a, k, w in
        re.findall(r"\| ([\d.]+) \| ([\d.]+)% \| ([\d.]+)% \| (\d+) \|", report)]
chosen = json.loads((ROOT / "reports" / "eval.json").read_text())["threshold"]
thr = [r[0] for r in rows]

fig, (ax, ax2) = plt.subplots(2, 1, figsize=(8, 5.4), sharex=True, gridspec_kw={"height_ratios": [3, 1.2]})
ax.plot(thr, [r[1] for r in rows], color=BLUE, lw=2, marker="o", ms=5, label="Messages routed correctly")
ax.plot(thr, [r[2] for r in rows], color=AQUA, lw=2, marker="o", ms=5, label="Clinic questions answered (not handed off)")
ax.set(ylabel="Share of messages", ylim=(0.4, 1.03),
       title="Answer threshold: answer as much as possible, never guess")
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
ax.legend(frameon=False, loc="lower left")

ax2.bar(thr, [r[3] for r in rows], width=0.006, color=[RED if r[3] else GRAY for r in rows])
ax2.set(ylabel="Wrong\nanswers", xlabel="Retrieval score needed before the bot answers")
ax2.set_yticks([0, 2, 4])
ax2.grid(axis="x", visible=False)

for a in (ax, ax2):
    a.axvline(chosen, color=INK, lw=1.2, ls="--")
ax.text(chosen + 0.002, 0.62, f"used: {chosen}", color=INK, fontsize=9.5)
ax2.text(0.15, 2.2, "no wrong answers from 0.09 upwards", color=MUTED, fontsize=9.5, ha="center")
fig.tight_layout()
fig.savefig(ROOT / "docs" / "threshold_sweep.png", dpi=150)
print("wrote docs/threshold_sweep.png")
