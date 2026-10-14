#!/usr/bin/env python3
"""Prueft, ob jeder modulvbergreifende Import der PRX-Module aufloest.

Hintergrund: die 120 Module sind `add_library(... SHARED EXCLUDE_FROM_ALL)` und haengen
nicht am Default-Target. Ein `ninja` ohne Target meldet darum "no work to do", obwohl die
Module veraltet sind — das Sammel-Target heisst `libs`. Ein gemischter Satz faellt sonst
erst beim Spielstart auf, und zwar als "Prozedureinsprungpunkt <NID> nicht gefunden", wo
Windows den Importeur nennt und nicht das Modul, dem der Export fehlt.

Aufruf:
    python tools/check_module_imports.py build/core/libs/libs [weitere.exe ...]
"""

import struct, sys, os, glob

def sections(d, pe):
    nsec = struct.unpack_from('<H', d, pe+6)[0]
    opt  = struct.unpack_from('<H', d, pe+20)[0]
    base = pe+24+opt
    return [(d[base+40*i:base+40*i+8].rstrip(b'\0').decode('latin1'),)+struct.unpack_from('<IIII', d, base+40*i+8) for i in range(nsec)]

def rva2off(secs, rva):
    for name,vsz,va,rsz,ra in secs:
        if va <= rva < va+max(vsz,rsz): return ra + (rva-va)
    return None

def load(path):
    d=open(path,'rb').read()
    pe=struct.unpack_from('<I', d, 0x3c)[0]
    opt=pe+24
    magic=struct.unpack_from('<H', d, opt)[0]
    ddir = opt + (112 if magic==0x20b else 96)
    return d, pe, ddir, sections(d,pe)

def exports(path):
    d,pe,ddir,secs = load(path)
    erva,esz = struct.unpack_from('<II', d, ddir)
    if not erva: return set()
    eo=rva2off(secs,erva)
    nnames, = struct.unpack_from('<I', d, eo+24)
    anames, = struct.unpack_from('<I', d, eo+32)
    no=rva2off(secs,anames)
    out=set()
    for i in range(nnames):
        nr,=struct.unpack_from('<I', d, no+4*i)
        so=rva2off(secs,nr); out.add(d[so:d.index(b'\0',so)].decode('latin1'))
    return out

def imports(path):
    d,pe,ddir,secs = load(path)
    irva,isz = struct.unpack_from('<II', d, ddir+8)
    if not irva: return {}
    io_=rva2off(secs,irva); out={}
    while True:
        olt,ts,fc,nrva,fthunk = struct.unpack_from('<IIIII', d, io_)
        if nrva==0: break
        so=rva2off(secs,nrva); dll=d[so:d.index(b'\0',so)].decode('latin1')
        names=[]; t=rva2off(secs, olt or fthunk)
        while True:
            v,=struct.unpack_from('<Q', d, t)
            if v==0: break
            if not (v>>63):
                hn=rva2off(secs, v & 0x7fffffff)
                names.append(d[hn+2:d.index(b'\0',hn+2)].decode('latin1'))
            t+=8
        out[dll]=names; io_+=20
    return out

libdir=sys.argv[1]
files = sorted(glob.glob(os.path.join(libdir,'*.prx'))) + sys.argv[2:]
exp = {os.path.basename(f).lower(): exports(f) for f in sorted(glob.glob(os.path.join(libdir,'*.prx')))}
bad=0; checked=0
for f in files:
    for dll,names in imports(f).items():
        k=dll.lower()
        if k not in exp: continue
        for n in names:
            checked+=1
            if n not in exp[k]:
                print(f'FEHLT  {n}  <- {os.path.basename(f)} importiert aus {dll}'); bad+=1
print(f'--- {len(files)} Images, {checked} modulinterne Importe geprueft, {bad} unaufloesbar')
