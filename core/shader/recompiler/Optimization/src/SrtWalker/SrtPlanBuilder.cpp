#include "Optimization/SrtWalker/SrtPlanBuilder.hpp"
#include "Optimization/SrtWalker/SrtDiagnostics.hpp"
#include "Optimization/SrtWalker/SrtInstructionPredicates.hpp"
#include "Optimization/SrtWalker/SrtRuntimeValidator.hpp"

#include "IntermediateRepresentation/IrBuilder.hpp"

#include <algorithm>
#include <stdexcept>
#include <unordered_map>
#include <vector>

namespace ShaderRecompiler::Detail {

void PlanBuilder::Run() {
    _program.Resources().srtReads.clear();
    _program.Metadata().dynamicReads.clear();
    for (auto& block : _program.Blocks()) {
        for (IrValue* inst : block->Instructions()) {
            const auto op = inst->Opcode();
            if (op == IrOpcode::LoadAddressU32 || op == IrOpcode::ReadConstBuffer) {
                const auto flags = inst->Flags<MemoryFlags>();
                if (flags.index < _program.Resources().memoryInfo.size()) {
                    const auto kind = _program.Resources().memoryInfo[flags.index].kind;
                    const bool crosswired = (op == IrOpcode::LoadAddressU32 && kind == ResourceKind::ScalarBuffer) || (op == IrOpcode::ReadConstBuffer && kind == ResourceKind::ScalarAddress);
                    if (crosswired) {
                        Fail(_program.Resources(), flags.pc, std::string(IrOpcodeName(op)) + " has incompatible scalar memory metadata");
                    }
                }
            }
            if (IsDescriptorHandle(inst->Opcode())) {
                for (std::size_t index = 0; index < inst->ArgumentCount(); index++) {
                    Collect(inst->Argument(index), 0);
                }
            }
        }
    }
    for (auto& block : _program.Blocks()) {
        for (IrValue* inst : block->Instructions()) {
            if (inst->Opcode() == IrOpcode::LoadAddressU32 && IsRawRead(_program.Resources(), *inst) && inst->Argument(1)->Resolve()->HasImmediate() && RuntimeValidator(_program.Resources(), RuntimeValueType::Any).Run(inst)) {
                Collect(inst, inst->Flags<MemoryFlags>().pc);
            }
        }
    }
    PatchReads();
}

void PlanBuilder::Collect(IrValue* initialRaw, std::uint32_t usePc) {
    if (initialRaw == nullptr) {
        return;
    }
    IrValue* root = initialRaw->Resolve();
    if (root->Opcode() == IrOpcode::Void) {
        return;
    }
    if (_visited.contains(root)) {
        return;
    }

    struct Frame {
        IrValue* inst;
        std::size_t nextArg;
    };

    std::vector<Frame> stack;
    std::unordered_map<IrValue*, std::size_t> inVisiting;

    stack.push_back({root, 0});
    inVisiting[root] = 0;

    while (!stack.empty()) {
        auto& frame = stack.back();
        IrValue* inst = frame.inst;

        if (frame.nextArg < inst->ArgumentCount()) {
            IrValue* argRaw = inst->Argument(frame.nextArg++);
            if (argRaw == nullptr) {
                continue;
            }
            IrValue* child = argRaw->Resolve();
            if (child->Opcode() == IrOpcode::Void) {
                continue;
            }

            auto visitIt = inVisiting.find(child);
            if (visitIt != inVisiting.end()) {
                const auto cycleStart = visitIt->second;
                bool containsPhi = false;
                for (std::size_t i = cycleStart; i < stack.size(); ++i) {
                    if (stack[i].inst->Opcode() == IrOpcode::Phi) {
                        containsPhi = true;
                        break;
                    }
                }
                if (containsPhi) {
                    continue;
                }
                Fail(_program.Resources(), usePc, "cyclic typed planning value " + std::string(IrOpcodeName(child->Opcode())) + " without a phi");
            }

            if (_visited.contains(child)) {
                continue;
            }

            inVisiting[child] = stack.size();
            stack.push_back({child, 0});
        } else {
            IrValue* processedInst = inst;
            inVisiting.erase(processedInst);
            stack.pop_back();
            _visited.insert(processedInst);

            if (!IsRawRead(_program.Resources(), *processedInst)) {
                continue;
            }
            IrValue* offset = processedInst->Argument(1)->Resolve();
            const auto foldable = offset->HasImmediate() && offset->Type() == IrType::U32 && RuntimeValidator(_program.Resources(), RuntimeValueType::Any).Run(processedInst);
            if (!foldable) {
                if (std::find(_program.Metadata().dynamicReads.begin(), _program.Metadata().dynamicReads.end(), processedInst) == _program.Metadata().dynamicReads.end()) {
                    _program.Metadata().dynamicReads.push_back(processedInst);
                }
                continue;
            }
            bool foundEquivalent = false;
            for (std::uint32_t slot = 0; slot < _program.Resources().srtReads.size(); slot++) {
                if (EquivalentValue(_program.Resources(), processedInst, _program.Resources().srtReads[slot].value)) {
                    _patches.push_back({processedInst, slot, false});
                    foundEquivalent = true;
                    break;
                }
            }
            if (!foundEquivalent) {
                const auto slot = static_cast<std::uint32_t>(_program.Resources().srtReads.size());
                _program.Resources().srtReads.push_back({processedInst, slot});
                _patches.push_back({processedInst, slot, true});
            }
        }
    }
}

void PlanBuilder::PatchReads() {
    IrBuilder builder(_program);
    for (const auto& patch : _patches) {
        IrBlock* block = patch.inst->Parent();
        if (block == nullptr) {
            throw std::runtime_error("SrtWalker::BuildPlan patched value has no parent block");
        }
        builder.SetInsertionPoint(*block);
        IrValue& resource = builder.Emit(IrOpcode::GetSrtResource, IrType::SrtResource, {});
        block->RemoveInstruction(&resource);
        block->InsertInstructionBefore(patch.inst, &resource);
        IrValue& slotConstant = builder.Constant(patch.slot);
        IrValue& flat = builder.Emit(IrOpcode::ReadConst, IrType::U32, {&resource, &slotConstant});
        block->RemoveInstruction(&flat);
        block->InsertInstructionBefore(patch.inst, &flat);
        for (const auto& use : std::vector<IrUse>(patch.inst->OperandUses())) {
            use.user->ReplaceArgument(use.operand, &flat);
        }
        for (auto& info : _program.Metadata().blockInfo) {
            if (info.condition != nullptr && info.condition->Resolve() == patch.inst) {
                info.condition = &flat;
            }
            if (info.indirectTarget != nullptr && info.indirectTarget->Resolve() == patch.inst) {
                info.indirectTarget = &flat;
            }
        }
        if (patch.keep) {
            const auto memory = patch.inst->Flags<MemoryFlags>().index;
            if (memory < _program.Resources().memoryInfo.size()) {
                _program.Resources().memoryInfo[memory].planningOnly = true;
            }
            const auto& irVal = builder.Emit(IrOpcode::ReferenceU32, IrType::Void, {patch.inst});
        }
    }
}

}
