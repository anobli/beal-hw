#!/usr/bin/env python3
"""Export JLCPCB fabrication and assembly files for a KiCad project.

Usage: jlcpcb-export.py <project.kicad_pro> <output_dir>

Produces in <output_dir>:
  <name>-gerbers.zip      Gerbers + Excellon drill files (upload for PCB quote)
  <name>-bom-jlcpcb.csv   BOM with JLCPCB column names (PCBA quote)
  <name>-cpl-jlcpcb.csv   Component placement list (PCBA quote)

Requires kicad-cli (KiCad 10) in PATH.
"""

import csv
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# Non-copper layers JLCPCB needs. Copper layers are read from the board.
TECH_LAYERS = [
    "F.Paste", "B.Paste",
    "F.Silkscreen", "B.Silkscreen",
    "F.Mask", "B.Mask",
    "Edge.Cuts",
]

# Symbol fields that may hold the LCSC part number, first match wins.
LCSC_FIELDS = ["LCSC", "LCSC Part #", "LCSC Part", "JLCPCB Part #"]
# Symbol fields that may hold the manufacturer part number, first match wins.
MPN_FIELDS = ["MPN", "Manufacturer_Part_Number"]
MFR_FIELDS = ["MANUFACTURER", "Manufacturer_Name", "Manufacturer"]


def run(*args):
    print("+ " + " ".join(args), flush=True)
    subprocess.run(["kicad-cli", *args], check=True)


def copper_layers(pcb):
    text = pcb.read_text()
    layers = re.findall(r'\(\d+\s+"([^"]+\.Cu)"\s+(?:signal|power|mixed|jumper)', text)
    if not layers:
        sys.exit(f"No copper layers found in {pcb}")
    return layers


def first(row, fields):
    for f in fields:
        if row.get(f, "").strip():
            return row[f].strip()
    return ""


def export_gerbers(pcb, out, name, tmp):
    gdir = tmp / "gerbers"
    gdir.mkdir()
    layers = ",".join(copper_layers(pcb) + TECH_LAYERS)
    run("pcb", "export", "gerbers", "--check-zones", "--layers", layers,
        "--output", f"{gdir}/", str(pcb))
    run("pcb", "export", "drill", "--format", "excellon", "--excellon-units", "mm",
        "--excellon-zeros-format", "decimal", "--excellon-oval-format", "alternate",
        "--excellon-separate-th", "--output", f"{gdir}/", str(pcb))
    archive = out / f"{name}-gerbers.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(gdir.iterdir()):
            z.write(f, f.name)
    print(f"Wrote {archive}")


def export_bom(sch, out, name, tmp):
    raw = tmp / "bom.csv"
    fields = ["Reference", "Value", "Footprint", "${QUANTITY}",
              *LCSC_FIELDS, *MPN_FIELDS, *MFR_FIELDS]
    run("sch", "export", "bom", "--exclude-dnp",
        "--fields", ",".join(fields), "--labels", ",".join(fields),
        "--group-by", ",".join(["Value", "Footprint", *LCSC_FIELDS, *MPN_FIELDS]),
        "--ref-range-delimiter", "",
        "--output", str(raw), str(sch))

    dst = out / f"{name}-bom-jlcpcb.csv"
    with raw.open(newline="") as fi, dst.open("w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #",
                    "MPN", "Manufacturer", "Quantity"])
        for row in csv.DictReader(fi):
            w.writerow([
                row["Value"],
                row["Reference"],
                row["Footprint"].split(":", 1)[-1],  # drop library prefix
                first(row, LCSC_FIELDS),
                first(row, MPN_FIELDS),
                first(row, MFR_FIELDS),
                row["${QUANTITY}"],
            ])
    print(f"Wrote {dst}")


def export_cpl(pcb, out, name, tmp):
    raw = tmp / "pos.csv"
    run("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both",
        "--exclude-dnp", "--output", str(raw), str(pcb))

    dst = out / f"{name}-cpl-jlcpcb.csv"
    with raw.open(newline="") as fi, dst.open("w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for row in csv.DictReader(fi):
            layer = "Top" if row["Side"].lower() == "top" else "Bottom"
            w.writerow([row["Ref"], f'{row["PosX"]}mm', f'{row["PosY"]}mm',
                        layer, row["Rot"]])
    print(f"Wrote {dst}")


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    pro = Path(sys.argv[1])
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    name = pro.stem
    pcb = pro.with_suffix(".kicad_pcb")
    sch = pro.with_suffix(".kicad_sch")

    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        export_gerbers(pcb, out, name, tmp)
        export_bom(sch, out, name, tmp)
        export_cpl(pcb, out, name, tmp)


if __name__ == "__main__":
    main()
