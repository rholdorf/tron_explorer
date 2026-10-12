"""LithTech RezMgr v1 archive reader/extractor (.rez).

Layout (little-endian):
  header (127 bytes text) + version, rootDirPos, rootDirSize, rootDirTime,
  nextWritePos, time, largestKeyAry, largestDirName, largestRezName,
  largestComment, isSorted(u8)
  directory block = sequence of entries:
    u32 type (1 = dir, 0 = resource)
    dir:  u32 pos, u32 size, u32 time, cstr name
    res:  u32 pos, u32 size, u32 time, u32 id, char[4] ext(reversed, NUL padded),
          u32 numKeys, cstr name, cstr comment, u32 keys[numKeys]
Resource file name = name + '.' + ext.
"""
import os
import struct
import sys

HEADER_TEXT = 127


class RezEntry:
    __slots__ = ("path", "pos", "size", "time")

    def __init__(self, path, pos, size, time):
        self.path, self.pos, self.size, self.time = path, pos, size, time


def _cstr(buf, off):
    end = buf.index(b"\0", off)
    return buf[off:end].decode("latin-1"), end + 1


def read_index(f):
    f.seek(HEADER_TEXT)
    (ver, root_pos, root_size, _rt, _nw, _t, _lk, _ld, _lr, _lc) = struct.unpack("<10I", f.read(40))
    if ver != 1:
        raise ValueError(f"unsupported rez version {ver}")
    out = []

    def walk(pos, size, prefix):
        f.seek(pos)
        buf = f.read(size)
        off = 0
        while off < size:
            (typ,) = struct.unpack_from("<I", buf, off)
            off += 4
            if typ == 1:
                p, s, t = struct.unpack_from("<3I", buf, off)
                off += 12
                name, off = _cstr(buf, off)
                walk(p, s, prefix + name + "/")
            elif typ == 0:
                p, s, t, _id = struct.unpack_from("<4I", buf, off)
                off += 16
                ext = buf[off:off + 4].rstrip(b"\0")[::-1].decode("latin-1")
                off += 4
                (nkeys,) = struct.unpack_from("<I", buf, off)
                off += 4
                name, off = _cstr(buf, off)
                _comment, off = _cstr(buf, off)
                off += 4 * nkeys
                fname = name + ("." + ext if ext else "")
                out.append(RezEntry(prefix + fname, p, s, t))
            else:
                raise ValueError(f"bad entry type {typ} at {pos + off - 4}")

    walk(root_pos, root_size, "")
    return out


def extract(rez_path, out_dir, lower=True):
    n = 0
    with open(rez_path, "rb") as f:
        for e in read_index(f):
            rel = e.path.lower() if lower else e.path
            dst = os.path.join(out_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            f.seek(e.pos)
            with open(dst, "wb") as o:
                remaining = e.size
                while remaining:
                    chunk = f.read(min(remaining, 1 << 20))
                    o.write(chunk)
                    remaining -= len(chunk)
            n += 1
    return n


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: rez.py list|extract file.rez [out_dir]")
        sys.exit(1)
    cmd, rez = sys.argv[1], sys.argv[2]
    if cmd == "list":
        with open(rez, "rb") as f:
            for e in read_index(f):
                print(f"{e.size:>10} {e.path}")
    else:
        print(extract(rez, sys.argv[3]), "files")
