#!/usr/bin/env python3
"""
Unpack PlayStation FSELF (Fake SELF) containers into standard ELF files for AnyPS5.
"""

import argparse
from pathlib import Path
import struct
import sys


def unself_file(src_path: Path, dst_path: Path) -> None:
    with open(src_path, "rb") as f_in:
        # Check SELF magic
        magic = f_in.read(4)
        if magic not in (b"\x4f\x15\x3d\x1d", b"\x54\x14\xf5\xee"):
            if magic.startswith(b"\x7fELF"):
                print(f"'{src_path.name}' is already an ELF file. Copying...")
                dst_path.write_bytes(src_path.read_bytes())
                return
            raise ValueError(f"Unknown file magic: {magic.hex()}")

        # Read number of segment entries at offset 0x18
        f_in.seek(0x18)
        num_entries = struct.unpack("<H", f_in.read(2))[0]

        # Read SELF segment table
        f_in.seek(0x20)
        entries = []
        for _ in range(num_entries):
            props, file_off, file_sz, mem_sz = struct.unpack("<QQQQ", f_in.read(32))
            seg_idx = (props >> 20) & 0xFFF
            has_digest = (props >> 16) & 1
            entries.append((props, file_off, file_sz, mem_sz, seg_idx, has_digest))

        # Find ELF header (typically at offset 0x1A0 / 416)
        f_in.seek(0)
        content_preview = f_in.read(0x1000)
        elf_start = content_preview.find(b"\x7fELF")
        if elf_start == -1:
            raise ValueError("No ELF header found inside SELF container.")

        f_in.seek(elf_start)
        ehdr = f_in.read(64)
        phoff = struct.unpack("<Q", ehdr[32:40])[0]
        phentsize = struct.unpack("<H", ehdr[54:56])[0]
        phnum = struct.unpack("<H", ehdr[56:58])[0]

        f_in.seek(elf_start + phoff)
        phdrs = []
        for _ in range(phnum):
            ph = f_in.read(phentsize)
            p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack(
                "<IIQQQQQQ", ph[:56]
            )
            phdrs.append((p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align))

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dst_path, "wb") as f_out:
            # Write ELF header + program headers
            f_in.seek(elf_start)
            headers = bytearray(f_in.read(phoff + phnum * phentsize))
            # Zero out section header offset and counts if sections were stripped
            struct.pack_into("<Q", headers, 40, 0)
            struct.pack_into("<HH", headers, 60, 0, 0)
            f_out.write(headers)

            # Map segment payload data
            data_entries = [e for e in entries if e[5] == 0]
            for props, file_off, file_sz, mem_sz, seg_idx, _ in data_entries:
                if seg_idx < len(phdrs):
                    target_offset = phdrs[seg_idx][2]
                    f_in.seek(file_off)
                    chunk = f_in.read(file_sz)
                    f_out.seek(target_offset)
                    f_out.write(chunk)

            # Map trailing non-entry segment (e.g. metadata/notes if after last entry)
            if data_entries:
                last_entry = data_entries[-1]
                last_self_end = last_entry[1] + last_entry[2]
                f_in.seek(0, 2)
                total_self = f_in.tell()
                if total_self > last_self_end:
                    remaining = total_self - last_self_end
                    f_in.seek(last_self_end)
                    extra = f_in.read(remaining)
                    # Place trailing segment at maximum p_offset of trailing headers
                    trailing_segs = [p for p in phdrs if p[2] > phdrs[last_entry[4]][2]]
                    target_offset = trailing_segs[0][2] if trailing_segs else phdrs[last_entry[4]][2] + last_entry[2]
                    f_out.seek(target_offset)
                    f_out.write(extra)

        print(f"Extracted ELF: {src_path.name} -> {dst_path}")


def main():
    parser = argparse.ArgumentParser(description="Convert PS5 FSELF containers to standard ELF binaries.")
    parser.add_argument("input", type=Path, help="Input SELF/FSELF file (e.g. eboot.bin or libc.prx)")
    parser.add_argument("output", type=Path, help="Output clean ELF file")
    args = parser.parse_args()

    try:
        unself_file(args.input, args.output)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
