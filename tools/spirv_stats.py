"""Reports the shape of a SPIR-V module the AnyPS5 recompiler produced.

    python spirv_stats.py <module.spv>...

Produce the input with the replay tool:
    agc_shader_replay --spv shader_<address>.req
Set APS5_SINGLE_LANE=all first to get the laneCount=1 variant for comparison.

Prints, per module: total words, the declaration/code split, function and basic
block counts, block size distribution, the opcode histogram by emitted words,
redundant constants, and whether the module declares buffer device addresses
(PhysicalStorageBufferAddresses), which is what makes a build "addressable" and
therefore ineligible for written-shadow staging.
"""
import collections
import json
import os
import pathlib
import struct
import sys

OP_CAPABILITY, OP_MEMORY_MODEL, OP_ENTRY_POINT = 17, 14, 15
OP_FUNCTION, OP_FUNCTION_END, OP_LABEL = 54, 56, 248
OP_CONSTANT, OP_CONSTANT_TRUE, OP_CONSTANT_FALSE = 43, 41, 42

GRAMMAR = "3rdparty/SPIRV-Headers/include/spirv/unified1/spirv.core.grammar.json"

def grammar():
    override = os.environ.get("ANYPS5_REPO")
    roots = [pathlib.Path(override)] if override else list(pathlib.Path(__file__).resolve().parents)
    for root in roots:
        path = root / GRAMMAR
        if path.is_file():
            break
    else:
        raise SystemExit(f"cannot find {GRAMMAR} above {__file__}; set ANYPS5_REPO")
    data = json.loads(path.read_text(encoding="utf-8"))
    names = {i["opcode"]: i["opname"] for i in data["instructions"]}
    caps, addr, exec_ = {}, {}, {}
    for kind in data["operand_kinds"]:
        table = {int(str(e["value"]), 0): e["enumerant"] for e in kind["enumerants"]} if "enumerants" in kind else {}
        if kind["kind"] == "Capability":
            caps = table
        if kind["kind"] == "AddressingModel":
            addr = table
        if kind["kind"] == "ExecutionModel":
            exec_ = table
    return names, caps, addr, exec_

def instructions(words):
    index = 5
    while index < len(words):
        count, opcode = words[index] >> 16, words[index] & 0xffff
        if count == 0:
            return
        yield opcode, count, words[index:index + count]
        index += count

def report(path, names, caps, addr, exec_):
    raw = pathlib.Path(path).read_bytes()
    words = struct.unpack("<%dI" % (len(raw) // 4), raw)
    if words[0] != 0x07230203:
        print(f"{path}: not a SPIR-V module")
        return
    counts, sizes = collections.Counter(), collections.Counter()
    declWords = codeWords = 0
    functions, blocks, blockSizes = [], 0, []
    inFunction, currentWords, currentBlocks, currentBlock = False, 0, 0, None
    capabilities, addressing, stage = [], None, None
    constants, trues, falses = collections.Counter(), collections.Counter(), collections.Counter()
    for opcode, count, operands in instructions(words):
        name = names.get(opcode, f"Op?{opcode}")
        counts[name] += 1
        sizes[name] += count
        if opcode == OP_CAPABILITY:
            capabilities.append(caps.get(operands[1], operands[1]))
        if opcode == OP_MEMORY_MODEL:
            addressing = addr.get(operands[1], operands[1])
        if opcode == OP_ENTRY_POINT:
            stage = exec_.get(operands[1], operands[1])
        if opcode == OP_CONSTANT and count >= 4:
            constants[(operands[1], tuple(operands[3:]))] += 1
        if opcode == OP_CONSTANT_TRUE:
            trues[operands[1]] += 1
        if opcode == OP_CONSTANT_FALSE:
            falses[operands[1]] += 1
        if opcode == OP_FUNCTION:
            inFunction, currentWords, currentBlocks, currentBlock = True, 0, 0, None
        if inFunction:
            codeWords += count
            currentWords += count
            if opcode == OP_LABEL:
                if currentBlock is not None:
                    blockSizes.append(currentBlock)
                currentBlock, currentBlocks, blocks = 0, currentBlocks + 1, blocks + 1
            elif currentBlock is not None:
                currentBlock += count
        else:
            declWords += count
        if opcode == OP_FUNCTION_END:
            if currentBlock is not None:
                blockSizes.append(currentBlock)
            functions.append((currentWords, currentBlocks))
            inFunction, currentBlock = False, None
    total = declWords + codeWords
    bda = [c for c in capabilities if "Physical" in str(c)]
    print(f"\n===== {pathlib.Path(path).name} =====")
    print(f"{total} words, {sum(counts.values())} instructions, {len(functions)} functions, {blocks} basic blocks")
    print(f"stage: {stage}; addressing model: {addressing}; "
          f"buffer device addresses: {'YES ' + ','.join(map(str, bda)) if bda else 'no'}")
    print(f"declarations {declWords} ({100 * declWords / total:.1f}%) | function code {codeWords} ({100 * codeWords / total:.1f}%)")
    if blockSizes:
        ordered = sorted(blockSizes)
        print(f"block words: max {ordered[-1]}, median {ordered[len(ordered) // 2]}, mean {sum(ordered) / len(ordered):.1f}")
    print(f"\n  {'opcode':<32}{'count':>9}{'words':>9}{'% words':>9}")
    for name, word in sizes.most_common(15):
        print(f"  {name:<32}{counts[name]:>9}{word:>9}{100 * word / total:>8.1f}%")
    print("\n  structure:")
    for key in ("OpFunction", "OpLabel", "OpLoopMerge", "OpSelectionMerge", "OpBranchConditional", "OpPhi", "OpFunctionCall", "OpVariable"):
        print(f"    {key:<24}{counts.get(key, 0):>8}")
    constantTotal, constantDistinct = sum(constants.values()), len(constants)
    redundant = 4 * (constantTotal - constantDistinct) + 3 * (sum(trues.values()) - len(trues)) + 3 * (sum(falses.values()) - len(falses))
    print("\n  constants:")
    print(f"    OpConstant       {constantTotal:>7} instructions, {constantDistinct:>5} distinct (type, value)")
    print(f"    OpConstantTrue   {sum(trues.values()):>7} instructions, {len(trues):>5} distinct types")
    print(f"    OpConstantFalse  {sum(falses.values()):>7} instructions, {len(falses):>5} distinct types")
    print(f"    redundant words  {redundant:>7} ({100 * redundant / total:.1f}% of the module)")
    if constants:
        (ctype, value), repeats = constants.most_common(1)[0]
        print(f"    most repeated    type %{ctype} value {value} x{repeats}")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    names, caps, addr, exec_ = grammar()
    for path in sys.argv[1:]:
        report(path, names, caps, addr, exec_)
    return 0

if __name__ == "__main__":
    sys.exit(main())
