"""Summarises the guest control flow graph the replay tool prints.

    agc_shader_replay --cfg shader_<address>.req > cfg.txt
    python cfg_summary.py cfg.txt

Reports the block and instruction counts, the back edges (one per loop) and,
for each loop body, its share of the structurizer's word estimate.

CAUTION: the `words=` field in the --cfg output is `estimatedSpirvWords`, a
heuristic the structurizer uses for its own cost decisions
(GraphBuilder.cpp:19). It is NOT a measurement of the emitted module. For real
sizes dump the module with --spv and use spirv_stats.py.
"""
import pathlib
import re
import sys

BLOCK = re.compile(
    r"block_(\d+) pc=(\S+) end=(\S+) inst=\[(\d+),(\d+)\) words=(\d+)\s*\n"
    r"\s*predecessors=\[([^\]]*)\] successors=\[([^\]]*)\]")

def run(path):
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    blocks = {}
    for match in BLOCK.finditer(text):
        blocks[int(match.group(1))] = {
            "pc": match.group(2),
            "instructions": int(match.group(5)) - int(match.group(4)),
            "words": int(match.group(6)),
            "successors": [int(x) for x in match.group(8).split(",") if x.strip()],
        }
    if not blocks:
        print(f"{path}: no blocks found")
        return
    words = sum(b["words"] for b in blocks.values())
    print(f"\n===== {pathlib.Path(path).name} =====")
    print(f"{len(blocks)} blocks, {sum(b['instructions'] for b in blocks.values())} RDNA instructions, "
          f"{words} estimated words (heuristic, see the module docstring)")
    back = [(block, successor) for block, data in sorted(blocks.items())
            for successor in data["successors"] if successor <= block]
    print(f"back edges: {back if back else 'none (loop free)'}")
    if back:
        print(f"\n{'loop':<14}{'blocks':>8}{'RDNA inst':>11}{'est. words':>12}{'% est':>8}")
        for block, successor in back:
            body = [index for index in blocks if successor <= index <= block]
            estimate = sum(blocks[index]["words"] for index in body)
            instructions = sum(blocks[index]["instructions"] for index in body)
            print(f"{f'[{successor}..{block}]':<14}{len(body):>8}{instructions:>11}{estimate:>12}{100 * estimate / words:>7.1f}%")
    print(f"\n{'block':<10}{'pc':>12}{'RDNA inst':>11}{'est. words':>12}")
    for block, data in sorted(blocks.items(), key=lambda kv: -kv[1]["words"])[:10]:
        print(f"block_{block:<4}{data['pc']:>12}{data['instructions']:>11}{data['words']:>12}")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for path in sys.argv[1:]:
        run(path)
    return 0

if __name__ == "__main__":
    sys.exit(main())
