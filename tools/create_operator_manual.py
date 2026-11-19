from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "Documentazione"
ASSETS_DIR = DOCS_DIR / "_manual_assets"
OUTPUT_PATH = DOCS_DIR / "Guida_Operativa_Doctor_Blade_Controller_V3_0_5.docx"

PAGE_WIDTH_DXA = 12240
PAGE_HEIGHT_DXA = 15840
CONTENT_WIDTH_DXA = 9360
TABLE_INDENT_DXA = 120

BLUE = "2E74B5"
DARK_BLUE = "1F4D78"
NAVY = "17365D"
INK = "1F2937"
MUTED = "5B6573"
LIGHT_BLUE = "E8EEF5"
LIGHT_GRAY = "F2F4F7"
LIGHT_GOLD = "FFF4CE"
LIGHT_RED = "FDE9E7"
LIGHT_GREEN = "E9F5EC"
WHITE = "FFFFFF"
RED = "9B1C1C"
GOLD = "7A5A00"
GREEN = "1F6B3A"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=80, start=120, bottom=80, end=120) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (
        ("top", top),
        ("start", start),
        ("bottom", bottom),
        ("end", end),
    ):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_borders(table, color="B7C3D0", size="4") -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = borders.find(qn(f"w:{edge}"))
        if tag is None:
            tag = OxmlElement(f"w:{edge}")
            borders.append(tag)
        tag.set(qn("w:val"), "single")
        tag.set(qn("w:sz"), size)
        tag.set(qn("w:space"), "0")
        tag.set(qn("w:color"), color)


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_row_cant_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    if tr_pr.find(qn("w:cantSplit")) is None:
        tr_pr.append(OxmlElement("w:cantSplit"))


def set_table_geometry(table, widths_dxa: list[int], indent_dxa=TABLE_INDENT_DXA) -> None:
    if sum(widths_dxa) != CONTENT_WIDTH_DXA:
        raise ValueError(f"Table widths must sum to {CONTENT_WIDTH_DXA}: {widths_dxa}")
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl = table._tbl
    tbl_pr = tbl.tblPr

    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(CONTENT_WIDTH_DXA))
    tbl_w.set(qn("w:type"), "dxa")

    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:w"), str(indent_dxa))
    tbl_ind.set(qn("w:type"), "dxa")

    grid = tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths_dxa:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)

    for row in table.rows:
        for index, cell in enumerate(row.cells):
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                tc_pr.append(tc_w)
            tc_w.set(qn("w:w"), str(widths_dxa[index]))
            tc_w.set(qn("w:type"), "dxa")
            set_cell_margins(cell)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER


def set_run_font(
    run,
    *,
    name="Calibri",
    size=11,
    color=INK,
    bold=False,
    italic=False,
) -> None:
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), name)
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)
    run.bold = bold
    run.italic = italic


def configure_styles(doc: Document) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal._element.rPr.rFonts.set(qn("w:ascii"), "Calibri")
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), "Calibri")
    normal.font.size = Pt(11)
    normal.font.color.rgb = RGBColor.from_string(INK)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.25

    for style_name, size, color, before, after in (
        ("Heading 1", 16, BLUE, 18, 10),
        ("Heading 2", 13, BLUE, 14, 7),
        ("Heading 3", 12, DARK_BLUE, 10, 5),
    ):
        style = doc.styles[style_name]
        style.font.name = "Calibri"
        style._element.rPr.rFonts.set(qn("w:ascii"), "Calibri")
        style._element.rPr.rFonts.set(qn("w:hAnsi"), "Calibri")
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True


def configure_page(doc: Document) -> None:
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(1)
    section.right_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)


def add_page_field(paragraph) -> None:
    run = paragraph.add_run()
    fld_char = OxmlElement("w:fldChar")
    fld_char.set(qn("w:fldCharType"), "begin")
    instr_text = OxmlElement("w:instrText")
    instr_text.set(qn("xml:space"), "preserve")
    instr_text.text = " PAGE "
    fld_char_end = OxmlElement("w:fldChar")
    fld_char_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_char)
    run._r.append(instr_text)
    run._r.append(fld_char_end)


def configure_header_footer(doc: Document) -> None:
    section = doc.sections[0]
    header = section.header
    p = header.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.space_after = Pt(0)
    set_run_font(
        p.add_run("DOCTOR BLADE CONTROLLER V3 | GUIDA OPERATIVA"),
        size=8.5,
        color=MUTED,
        bold=True,
    )

    footer = section.footer
    table = footer.add_table(rows=1, cols=2, width=Inches(6.5))
    set_repeat_table_header(table.rows[0])
    set_table_geometry(table, [7200, 2160], indent_dxa=0)
    table._tbl.tblPr.remove(table._tbl.tblPr.find(qn("w:tblBorders"))) if table._tbl.tblPr.find(qn("w:tblBorders")) is not None else None
    left = table.cell(0, 0).paragraphs[0]
    left.alignment = WD_ALIGN_PARAGRAPH.LEFT
    left.paragraph_format.space_after = Pt(0)
    set_run_font(left.add_run("Versione software 3.0.5 | 9 giugno 2026"), size=8.5, color=MUTED)
    right = table.cell(0, 1).paragraphs[0]
    right.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    right.paragraph_format.space_after = Pt(0)
    set_run_font(right.add_run("Pagina "), size=8.5, color=MUTED)
    add_page_field(right)


def add_numbering_instance(doc: Document, abstract_id: int) -> int:
    numbering = doc.part.numbering_part.element
    existing_num = [
        int(node.get(qn("w:numId")))
        for node in numbering.findall(qn("w:num"))
    ]
    num_id = max(existing_num, default=0) + 1
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(num_id))
    abstract_ref = OxmlElement("w:abstractNumId")
    abstract_ref.set(qn("w:val"), str(abstract_id))
    num.append(abstract_ref)
    level_override = OxmlElement("w:lvlOverride")
    level_override.set(qn("w:ilvl"), "0")
    start_override = OxmlElement("w:startOverride")
    start_override.set(qn("w:val"), "1")
    level_override.append(start_override)
    num.append(level_override)
    numbering.append(num)
    return num_id


def add_numbering_definitions(doc: Document) -> tuple[int, int, int]:
    numbering = doc.part.numbering_part.element
    existing_abstract = [
        int(node.get(qn("w:abstractNumId")))
        for node in numbering.findall(qn("w:abstractNum"))
    ]
    existing_num = [
        int(node.get(qn("w:numId")))
        for node in numbering.findall(qn("w:num"))
    ]
    abstract_start = max(existing_abstract, default=0) + 1
    num_start = max(existing_num, default=0) + 1

    def add_definition(abstract_id: int, num_id: int, fmt: str, text: str) -> None:
        abstract = OxmlElement("w:abstractNum")
        abstract.set(qn("w:abstractNumId"), str(abstract_id))
        multi = OxmlElement("w:multiLevelType")
        multi.set(qn("w:val"), "singleLevel")
        abstract.append(multi)
        lvl = OxmlElement("w:lvl")
        lvl.set(qn("w:ilvl"), "0")
        start = OxmlElement("w:start")
        start.set(qn("w:val"), "1")
        lvl.append(start)
        num_fmt = OxmlElement("w:numFmt")
        num_fmt.set(qn("w:val"), fmt)
        lvl.append(num_fmt)
        lvl_text = OxmlElement("w:lvlText")
        lvl_text.set(qn("w:val"), text)
        lvl.append(lvl_text)
        lvl_jc = OxmlElement("w:lvlJc")
        lvl_jc.set(qn("w:val"), "left")
        lvl.append(lvl_jc)
        p_pr = OxmlElement("w:pPr")
        tabs = OxmlElement("w:tabs")
        tab = OxmlElement("w:tab")
        tab.set(qn("w:val"), "num")
        tab.set(qn("w:pos"), "540")
        tabs.append(tab)
        p_pr.append(tabs)
        ind = OxmlElement("w:ind")
        ind.set(qn("w:left"), "540")
        ind.set(qn("w:hanging"), "270")
        p_pr.append(ind)
        spacing = OxmlElement("w:spacing")
        spacing.set(qn("w:after"), "80")
        spacing.set(qn("w:line"), "300")
        spacing.set(qn("w:lineRule"), "auto")
        p_pr.append(spacing)
        lvl.append(p_pr)
        abstract.append(lvl)
        numbering.append(abstract)

        num = OxmlElement("w:num")
        num.set(qn("w:numId"), str(num_id))
        abstract_ref = OxmlElement("w:abstractNumId")
        abstract_ref.set(qn("w:val"), str(abstract_id))
        num.append(abstract_ref)
        numbering.append(num)

    add_definition(abstract_start, num_start, "bullet", "•")
    add_definition(abstract_start + 1, num_start + 1, "decimal", "%1.")
    return num_start, num_start + 1, abstract_start + 1


def add_list_item(doc: Document, text: str, num_id: int) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.25
    p_pr = p._p.get_or_add_pPr()
    num_pr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    num_id_node = OxmlElement("w:numId")
    num_id_node.set(qn("w:val"), str(num_id))
    num_pr.append(ilvl)
    num_pr.append(num_id_node)
    p_pr.append(num_pr)
    p.add_run(text)


def add_callout(doc: Document, title: str, text: str, kind="note") -> None:
    fill, title_color = {
        "warning": (LIGHT_RED, RED),
        "caution": (LIGHT_GOLD, GOLD),
        "positive": (LIGHT_GREEN, GREEN),
        "note": (LIGHT_BLUE, DARK_BLUE),
    }[kind]
    table = doc.add_table(rows=1, cols=1)
    set_repeat_table_header(table.rows[0])
    set_table_geometry(table, [CONTENT_WIDTH_DXA])
    set_table_borders(table, color=title_color, size="8")
    cell = table.cell(0, 0)
    set_cell_shading(cell, fill)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(3)
    set_run_font(p.add_run(f"{title}: "), bold=True, color=title_color)
    set_run_font(p.add_run(text), color=INK)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_table(
    doc: Document,
    headers: list[str],
    rows: list[list[str]],
    widths_dxa: list[int],
    *,
    font_size=9.5,
) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    set_table_geometry(table, widths_dxa)
    set_table_borders(table)
    header = table.rows[0]
    set_repeat_table_header(header)
    set_row_cant_split(header)
    for index, text in enumerate(headers):
        cell = header.cells[index]
        set_cell_shading(cell, LIGHT_BLUE)
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        set_run_font(p.add_run(text), size=font_size, bold=True, color=NAVY)

    for row_values in rows:
        row = table.add_row()
        set_row_cant_split(row)
        cells = row.cells
        for index, text in enumerate(row_values):
            p = cells[index].paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.1
            set_run_font(p.add_run(text), size=font_size, color=INK)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_label_detail_table(doc: Document, rows: list[tuple[str, str]]) -> None:
    table = doc.add_table(rows=0, cols=2)
    for label, detail in rows:
        cells = table.add_row().cells
        set_cell_shading(cells[0], LIGHT_GRAY)
        p0 = cells[0].paragraphs[0]
        p0.paragraph_format.space_after = Pt(0)
        set_run_font(p0.add_run(label), size=10, bold=True, color=NAVY)
        p1 = cells[1].paragraphs[0]
        p1.paragraph_format.space_after = Pt(0)
        set_run_font(p1.add_run(detail), size=10, color=INK)
    if table.rows:
        set_repeat_table_header(table.rows[0])
    set_table_geometry(table, [2700, 6660])
    set_table_borders(table)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def make_system_diagram(path: Path) -> None:
    width, height = 1600, 720
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font_regular = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 30)
    font_bold = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 32)
    font_small = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 24)

    boxes = [
        (60, 230, 340, 470, "PC Windows 11", "Doctor Blade\nController V3"),
        (500, 210, 890, 490, "SKR Mini E3 V3", "Marlin + USB serial\nTMC2209 + bed output"),
        (1080, 50, 1510, 200, "Motore NEMA 17", "Movimento asse X"),
        (1080, 270, 1510, 420, "Fine corsa X-min", "Riferimento homing"),
        (1080, 490, 1510, 640, "Heater + termistore", "Tappeto silicone 80 W"),
    ]

    for x1, y1, x2, y2, title, subtitle in boxes:
        draw.rounded_rectangle(
            (x1, y1, x2, y2),
            radius=22,
            fill="#F4F7FA",
            outline="#2E74B5",
            width=4,
        )
        title_box = draw.textbbox((0, 0), title, font=font_bold)
        title_width = title_box[2] - title_box[0]
        draw.text(
            ((x1 + x2 - title_width) / 2, y1 + 36),
            title,
            font=font_bold,
            fill="#17365D",
        )
        lines = subtitle.splitlines()
        y = y1 + 98
        for line in lines:
            line_box = draw.textbbox((0, 0), line, font=font_regular)
            line_width = line_box[2] - line_box[0]
            draw.text(
                ((x1 + x2 - line_width) / 2, y),
                line,
                font=font_regular,
                fill="#1F2937",
            )
            y += 40

    def arrow(start, end, label):
        draw.line((start, end), fill="#526D82", width=7)
        x2, y2 = end
        draw.polygon(
            [(x2, y2), (x2 - 22, y2 - 13), (x2 - 22, y2 + 13)],
            fill="#526D82",
        )
        mid_x = (start[0] + end[0]) // 2
        mid_y = (start[1] + end[1]) // 2
        label_box = draw.textbbox((0, 0), label, font=font_small)
        draw.rectangle(
            (
                mid_x - (label_box[2] - label_box[0]) / 2 - 8,
                mid_y - 24,
                mid_x + (label_box[2] - label_box[0]) / 2 + 8,
                mid_y + 15,
            ),
            fill="white",
        )
        draw.text(
            (mid_x - (label_box[2] - label_box[0]) / 2, mid_y - 21),
            label,
            font=font_small,
            fill="#526D82",
        )

    arrow((340, 350), (500, 350), "USB / COM")
    arrow((890, 270), (1080, 125), "STEP/DIR")
    arrow((890, 350), (1080, 345), "INPUT")
    arrow((890, 430), (1080, 565), "POWER + TEMP")
    image.save(path)


def add_title_page(doc: Document, diagram_path: Path) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(54)
    p.paragraph_format.space_after = Pt(8)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(
        p.add_run("DOCTOR BLADE CONTROLLER V3"),
        size=28,
        color=NAVY,
        bold=True,
    )
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(22)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(
        p.add_run("Manuale operativo, sicurezza e troubleshooting"),
        size=15,
        color=BLUE,
        bold=True,
    )
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(26)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(
        p.add_run(
            "Sistema custom con asse X NEMA 17, fine corsa X-min, piano riscaldato "
            "e scheda BIGTREETECH SKR Mini E3 V3"
        ),
        size=11.5,
        color=MUTED,
        italic=True,
    )
    doc.add_picture(str(diagram_path), width=Inches(6.25))
    inline = doc.inline_shapes[-1]._inline
    inline.docPr.set(
        "descr",
        "Schema a blocchi del sistema: PC Windows collegato via USB alla scheda "
        "SKR Mini E3 V3, che controlla motore X, fine corsa, heater e termistore.",
    )
    inline.docPr.set("title", "Architettura Doctor Blade Controller V3")
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(20)
    p.paragraph_format.space_after = Pt(0)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(p.add_run("Versione software 3.0.5"), size=11, color=NAVY, bold=True)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(p.add_run("Data documento: 9 giugno 2026"), size=10, color=MUTED)
    p.add_run().add_break(WD_BREAK.PAGE)


def add_contents(doc: Document, number_id: int) -> None:
    doc.add_heading("Indice operativo", level=1)
    contents = [
        "Scopo, limiti e responsabilità dell’operatore",
        "Descrizione del sistema e prerequisiti",
        "Installazione e avvio",
        "Prima messa in servizio",
        "Connessione alla scheda e stato Ready",
        "Homing e controllo del movimento",
        "Gestione del piano riscaldato",
        "Profili di coating",
        "Calibrazione dell’asse X",
        "Arresti, emergenze e spegnimento",
        "Manutenzione e checklist",
        "Troubleshooting",
        "Riferimento G-code e fonti",
    ]
    for item in contents:
        add_list_item(doc, item, number_id)
    add_callout(
        doc,
        "Regola fondamentale",
        "Dopo qualsiasi stop, perdita di passi, reset della scheda, disconnessione, "
        "spegnimento motori o modifica dei passi/mm, eseguire nuovamente Home X.",
        "warning",
    )


def build_manual() -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    diagram_path = ASSETS_DIR / "schema_sistema_v3.png"
    make_system_diagram(diagram_path)

    doc = Document()
    configure_page(doc)
    configure_styles(doc)
    configure_header_footer(doc)
    bullet_id, number_id, decimal_abstract_id = add_numbering_definitions(doc)
    add_title_page(doc, diagram_path)
    add_contents(doc, number_id)

    doc.add_heading("1. Scopo, limiti e responsabilità", level=1)
    doc.add_paragraph(
        "Questa guida descrive l’uso di Doctor Blade Controller V3 per un sistema "
        "da laboratorio con un solo asse X, piano in vetro temprato, tappeto "
        "riscaldante in silicone, fine corsa X-min e controllo Marlin tramite USB."
    )
    add_callout(
        doc,
        "Limite di sicurezza",
        "Il software non è un PLC di sicurezza e non sostituisce un arresto fisico "
        "che interrompa l’alimentazione. I comandi software dipendono da Windows, "
        "USB, firmware Marlin e alimentazione della scheda.",
        "warning",
    )
    for item in [
        "Non lasciare il sistema riscaldato o in movimento senza supervisione.",
        "Tenere mani, cavi, utensili e indumenti fuori dalla corsa del carrello.",
        "Verificare che il blade non possa urtare il telaio, il vetro o il fine corsa.",
        "Usare cablaggi, connettori, fusibili e alimentatore dimensionati da personale competente.",
        "Non aumentare limiti termici, corsa, velocità o accelerazione senza una validazione meccanica e termica.",
        "Dopo una modifica firmware ripetere tutte le prove di prima messa in servizio.",
    ]:
        add_list_item(doc, item, bullet_id)

    doc.add_heading("2. Sistema controllato", level=1)
    add_label_detail_table(
        doc,
        [
            ("Asse", "Un asse X lineare, mosso da motore NEMA 17."),
            ("Controllore", "BIGTREETECH SKR Mini E3 V3 con firmware Marlin."),
            ("Riferimento", "Fine corsa meccanico X-min usato per G28 X."),
            ("Riscaldamento", "Tappeto in silicone da 80 W sotto il vetro, controllato come heated bed Marlin."),
            ("Sensore", "Termistore collegato all’ingresso bed della scheda."),
            ("Interfaccia", "PC Windows 11 tramite porta USB seriale COM."),
            ("Assi esclusi", "Nessuna logica applicativa per Y, Z o estrusore."),
        ],
    )
    add_callout(
        doc,
        "Assorbimento indicativo",
        "A 12 V, un heater da 80 W assorbe circa 6,7 A. Verificare la tensione "
        "reale e dimensionare alimentatore, fusibile, cavi, connettori e MOSFET "
        "sulla corrente effettiva e sulle specifiche ufficiali.",
        "caution",
    )

    doc.add_heading("3. Requisiti firmware Marlin", level=1)
    doc.add_paragraph(
        "La V3 usa comandi Marlin standard. Prima dell’uso verificare almeno i "
        "seguenti elementi nella configurazione firmware:"
    )
    firmware_rows = [
        ["THERMAL_PROTECTION_BED", "Obbligatoria", "Spegne il heater in caso di riscaldamento anomalo o instabilità."],
        ["EMERGENCY_PARSER", "Fortemente raccomandata", "Permette a M108, M112 e M410 di essere intercettati anche durante attese bloccanti."],
        ["EEPROM_SETTINGS", "Necessaria per M500", "Consente di salvare la calibrazione M92 X."],
        ["M503 disponibile", "Necessaria per lettura calibrazione", "La V3 legge i passi X dalla riga M92 restituita da M503."],
        ["USE_XMIN_PLUG", "Necessaria", "Abilita il fine corsa X-min usato dall’homing."],
        ["X_HOME_DIR -1", "Obbligatoria", "Definisce il fine corsa a X=0 come riferimento minimo."],
        ["INVERT_X_DIR", "Dipende dal cablaggio", "Impostare il valore che fa muovere -X verso home e +X in allontanamento."],
        ["Limiti software X", "Raccomandati", "Aggiungono una protezione firmware oltre al limite applicativo."],
    ]
    add_table(doc, ["Opzione", "Stato", "Motivo"], firmware_rows, [2500, 2200, 4660], font_size=9.5)

    doc.add_heading("4. Installazione del software", level=1)
    doc.add_heading("4.1 Uso dell’eseguibile", level=2)
    number_id = add_numbering_instance(doc, decimal_abstract_id)
    for step in [
        "Aprire la cartella dist della release V3.",
        "Avviare DoctorBladeControllerV306.exe.",
        "Se Windows SmartScreen blocca l’avvio, verificare provenienza e hash del file prima di autorizzarlo.",
        "Non eseguire contemporaneamente altri programmi che tengono aperta la stessa porta COM.",
    ]:
        add_list_item(doc, step, number_id)
    doc.add_heading("4.2 Avvio da sorgente", level=2)
    add_callout(
        doc,
        "Comandi",
        "Installare le dipendenze con “python -m pip install -r requirements.txt”, "
        "quindi avviare con “python main.py”. Per creare l’eseguibile usare build_exe.bat.",
        "note",
    )

    doc.add_heading("5. Prima messa in servizio", level=1)
    doc.add_paragraph(
        "Eseguire questa procedura con blade rimosso o in posizione non pericolosa, "
        "heater disattivato e velocità iniziale bassa."
    )
    commissioning = [
        "Controllare serraggi, scorrimento manuale dell’attuatore e assenza di ostacoli.",
        "Verificare che il fine corsa sia cablato sul connettore X-min corretto.",
        "Nell’app premere Check X Endstop (M119) con leva libera: deve comparire OPEN.",
        "Tenere premuta la leva e ripetere Check X Endstop (M119): deve comparire TRIGGERED; rilasciandola deve tornare OPEN.",
        "Verificare la direzione di homing: G28 X deve muovere in direzione -X verso il fine corsa.",
        "Provare Home X tenendo pronto l’arresto fisico. Premere manualmente il fine corsa se necessario durante la prima prova.",
        "Dopo l’homing, provare un piccolo jog +X a bassa velocità: il carrello deve allontanarsi dal fine corsa e la coordinata deve aumentare.",
        "Impostare una corsa software inferiore alla corsa meccanica realmente disponibile.",
        "Eseguire jog da 1 mm a bassa velocità in entrambe le direzioni.",
        "Verificare la temperatura a freddo confrontandola con un riferimento ambientale plausibile.",
        "Comandare un setpoint basso e osservare che la temperatura salga gradualmente; poi usare Heater Off e verificare il calo.",
        "Solo dopo questi controlli montare il blade ed eseguire una corsa di prova senza materiale.",
    ]
    number_id = add_numbering_instance(doc, decimal_abstract_id)
    for step in commissioning:
        add_list_item(doc, step, number_id)
    add_callout(
        doc,
        "Convenzione asse X",
        "Con home a X=0, -X deve andare verso il fine corsa e +X deve "
        "allontanarsene. Se +X va verso home, correggere INVERT_X_DIR nel "
        "firmware: non estendere la corsa applicativa a coordinate negative.",
        "warning",
    )

    doc.add_heading("6. Connessione e inizializzazione", level=1)
    number_id = add_numbering_instance(doc, decimal_abstract_id)
    for step in [
        "Accendere in sicurezza scheda e alimentatore macchina.",
        "Collegare il cavo USB al PC.",
        "Premere Refresh e selezionare la porta COM corretta; in alternativa inserirla nel campo Manual COM.",
        "Scegliere 115200 o 250000 baud in accordo con Marlin.",
        "Premere Connect.",
        "Attendere il passaggio da Initializing a Ready. La V3 attende il riavvio della scheda e invia M115.",
        "Eseguire Home X prima di qualsiasi movimento normale.",
    ]:
        add_list_item(doc, step, number_id)
    add_callout(
        doc,
        "Reset della scheda",
        "Se nel log compare la riga start, la V3 considera Marlin riavviato, "
        "annulla l’operazione, invalida la posizione X e ripete l’inizializzazione.",
        "note",
    )

    doc.add_heading("7. Movimento manuale", level=1)
    add_label_detail_table(
        doc,
        [
            ("Home X", "Esegue M119; con una stima oltre 40 mm propone una corsa rapida controllata fino alla zona lenta, ripete M119 e infine invia G28 X."),
            ("Estimated distance to home", "Stima non persistente: 0–40 mm usa il solo G28 lento; oltre 40 mm propone una corsa a 10 mm/s pari a stima meno 40 mm."),
            ("Read Position", "Richiede a Marlin la posizione X corrente."),
            ("Check X Endstop (M119)", "Legge X-min senza muovere il carrello: OPEN a leva libera, TRIGGERED a leva premuta."),
            ("Jog -X (toward home)", "Riduce X e si avvicina al fine corsa X-min."),
            ("Jog +X (away from home)", "Aumenta X e si allontana dal fine corsa lungo la corsa utile."),
            ("Move to X", "Esegue un movimento assoluto entro il limite software."),
            ("Speed", "Inserita in mm/s e convertita in feedrate Marlin mm/min."),
            ("Acceleration", "Applicata come accelerazione travel M204 T."),
            ("Travel limit", "Limite applicativo 0…X; deve essere inferiore alla corsa meccanica sicura."),
        ],
    )
    add_callout(
        doc,
        "Leva premuta a macchina ferma",
        "Il fine corsa non genera un evento visibile da solo. Premere Check X "
        "Endstop (M119) mentre la leva è libera e poi mentre è premuta. Non "
        "eseguire Home X se il valore non cambia.",
        "warning",
    )
    add_callout(
        doc,
        "Override senza homing",
        "L’opzione Allow movement before homing elimina la garanzia del limite "
        "software perché la posizione fisica non è nota. Usarla solo durante "
        "diagnostica controllata e confermarla a ogni sessione.",
        "warning",
    )
    add_callout(
        doc,
        "Homing a due stadi",
        "Con firmware V1.0.2, gli ultimi 40 mm restano affidati a Marlin: primo "
        "contatto a 5 mm/s, arretramento di 4 mm e secondo contatto a 2,5 mm/s. "
        "Prima della corsa rapida l’app invia M120, così X-min può arrestare il "
        "movimento anche senza una coordinata valida. La stima viene azzerata "
        "dopo l’avvio e non viene salvata.",
        "positive",
    )
    doc.add_heading("7.1 Scelta iniziale dei parametri", level=2)
    doc.add_paragraph(
        "Per la prima prova usare valori deliberatamente conservativi. Aumentare "
        "velocità e accelerazione solo dopo aver verificato assenza di perdita "
        "passi, vibrazioni, flessioni della barra e sollecitazioni sul blade."
    )

    doc.add_heading("8. Piano riscaldato", level=1)
    add_label_detail_table(
        doc,
        [
            ("Set Bed Temperature", "Invia M140: imposta il target senza attendere."),
            ("Set and Wait", "Invia M190: attende il raggiungimento del target."),
            ("Heater Off", "Interrompe eventuali attese, ferma l’operazione attiva e invia M140 S0."),
            ("Safety limit", "Oltre questa soglia l’app richiede conferma esplicita."),
            ("Polling", "La V3 invia M105 in background e attende l’ok associato."),
        ],
    )
    for item in [
        "Non coprire il termistore e non separarlo termicamente dal piano controllato.",
        "Evitare gradienti rapidi o raffreddamenti localizzati sul vetro temprato.",
        "Se la temperatura sale quando il target è 0 °C, togliere alimentazione con l’arresto fisico.",
        "Un errore Heating failed o Thermal runaway richiede ispezione di heater, termistore, fissaggio e firmware; non limitarsi a riavviare.",
    ]:
        add_list_item(doc, item, bullet_id)

    doc.add_heading("9. Profili di coating", level=1)
    doc.add_paragraph(
        "Un profilo è una sequenza JSON di segmenti. Ogni segmento contiene "
        "posizione X assoluta, velocità, accelerazione, dwell e temperatura bed opzionale."
    )
    number_id = add_numbering_instance(doc, decimal_abstract_id)
    for step in [
        "Eseguire Home X.",
        "Impostare il limite di corsa software corretto.",
        "Aggiungere i segmenti e verificare ogni target X.",
        "Usare Wait for temperature solo quando è necessario attendere la stabilizzazione.",
        "Salvare il profilo JSON prima della prova.",
        "Eseguire una prima corsa senza materiale e con temperatura ridotta o disattivata.",
        "Premere Run Profile e monitorare posizione, temperatura e log.",
        "Con Stop Profile la V3 invia M108, M410 e M140 S0; dopo lo stop è obbligatorio un nuovo Home X.",
    ]:
        add_list_item(doc, step, number_id)
    add_callout(
        doc,
        "Operazione singola",
        "La V3 consente una sola operazione normale alla volta. Questo impedisce "
        "che jog, homing, profilo e calibrazione mescolino comandi G90/G91/G1.",
        "positive",
    )

    doc.add_heading("10. Calibrazione asse X", level=1)
    doc.add_paragraph(
        "La calibrazione corregge i passi/mm in base a una distanza fisica misurata "
        "con Keyence IL-S025 o altro riferimento esterno. Il software non comunica "
        "direttamente con il sensore."
    )
    calibration_steps = [
        "Connettere la scheda e attendere Ready.",
        "Premere Read X Steps/mm from Marlin. La V3 invia M503 e legge M92 X.",
        "Eseguire Home X.",
        "Portare il carrello in una posizione da cui la corsa positiva scelta resti entro il limite software.",
        "Inserire Commanded travel distance.",
        "Premere Run +X Calibration Stroke.",
        "Misurare lo spostamento reale senza includere gioco, flessione o movimento del supporto sensore.",
        "Inserire Measured travel distance.",
        "Controllare il valore calcolato: new_steps = current_steps × commanded / measured.",
        "Premere Apply X Steps/mm e confermare M92 X seguito da M500.",
        "Eseguire nuovamente Home X e ripetere la misura di verifica.",
    ]
    number_id = add_numbering_instance(doc, decimal_abstract_id)
    for step in calibration_steps:
        add_list_item(doc, step, number_id)
    add_callout(
        doc,
        "Qualità della misura",
        "Usare una corsa sufficientemente lunga, ripetere almeno tre misure nella "
        "stessa direzione e separare l’errore di scala da backlash, slittamento o perdita passi.",
        "caution",
    )

    doc.add_heading("11. Arresti e spegnimento", level=1)
    stop_rows = [
        ["Quick Stop", "M410 + G90", "Ferma istantaneamente gli stepper e ripristina il posizionamento assoluto. La posizione resta inaffidabile.", "Eseguire Home X."],
        ["Stop Profile", "M108 + M410 + M140 S0", "Interrompe attesa termica, movimento e heater.", "Eseguire Home X e verificare la temperatura."],
        ["Heater Off", "M108 + M410 + M140 S0 se necessario", "Privilegia lo spegnimento termico e annulla l’operazione attiva.", "Verificare che il target vada a 0."],
        ["Emergency Stop", "M112", "Arresto completo e latched: Marlin entra in stato KILLED.", "Togliere alimentazione se il rischio persiste; resettare o spegnere/riaccendere la scheda, riconnettere e rifare Home X."],
        ["Arresto fisico", "Interruzione alimentazione", "Indipendente dal software.", "Usare quando USB, PC o firmware non rispondono."],
    ]
    add_table(
        doc,
        ["Comando", "G-code", "Effetto", "Dopo l’arresto"],
        stop_rows,
        [1700, 2100, 3000, 2560],
        font_size=9,
    )
    add_callout(
        doc,
        "EMERGENCY_PARSER",
        "Senza EMERGENCY_PARSER, M108/M112/M410 possono essere ritardati dietro "
        "un comando bloccante. L’arresto fisico resta l’unico controllo indipendente.",
        "warning",
    )

    doc.add_heading("12. Checklist operative", level=1)
    doc.add_heading("12.1 Prima di ogni ciclo", level=2)
    before_items = [
        "Area di corsa libera e blade fissato correttamente.",
        "Vetro integro, pulito e correttamente supportato.",
        "Fine corsa e cablaggio senza danni visibili.",
        "Termistore aderente e cablaggio heater integro.",
        "Porta COM corretta e stato Ready.",
        "Home X completato.",
        "Limite di corsa, velocità, accelerazione e profilo verificati.",
        "Arresto fisico accessibile.",
    ]
    for item in before_items:
        add_list_item(doc, f"☐ {item}", bullet_id)
    doc.add_heading("12.2 Dopo il ciclo", level=2)
    after_items = [
        "Inviare Heater Off e verificare target 0 °C.",
        "Portare il carrello in una posizione sicura solo se la posizione è ancora valida.",
        "Disabilitare i motori quando opportuno; ricordare che sarà necessario rifare Home X.",
        "Disconnettere l’app e togliere alimentazione secondo la procedura di laboratorio.",
        "Registrare anomalie, errori Marlin e modifiche ai parametri.",
    ]
    for item in after_items:
        add_list_item(doc, f"☐ {item}", bullet_id)

    doc.add_page_break()
    doc.add_heading("13. Troubleshooting", level=1)
    doc.add_paragraph(
        "Prima di intervenire, mettere la macchina in condizione sicura. Se esiste "
        "un rischio termico o meccanico immediato, usare l’arresto fisico."
    )

    doc.add_heading("13.1 Connessione e avvio", level=2)
    connection_rows = [
        ["Nessuna porta COM", "Cavo solo alimentazione, driver USB, scheda non alimentata.", "Gestione dispositivi; provare altro cavo/porta.", "Usare un cavo dati; reinstallare driver appropriato; verificare alimentazione."],
        ["Access denied / porta occupata", "Un altro programma ha aperto la COM.", "Chiudere terminali, IDE, slicer o altra istanza app.", "Chiudere il processo concorrente e riconnettere."],
        ["Resta su Initializing", "Baud errato, reset lento, firmware non risponde a M115.", "Controllare baud e log; attendere 15 s.", "Disconnettere, verificare Marlin e riconnettere."],
        ["Sembra bloccato dopo Emergency Stop", "M112 ha posto Marlin nello stato latched KILLED, come previsto.", "Nel log compare M112 e l'app indica E-STOP: RESET BOARD.", "Resettare o spegnere/riaccendere la scheda, poi riconnettere e rifare Home X. Non inviare M999 automaticamente."],
        ["Disconnessioni casuali", "Cavo USB, disturbi EMI, alimentazione instabile.", "Cercare “Serial connection lost” o “start” nel log.", "Cavo corto schermato, separare potenza/segnale, verificare alimentatore e massa."],
        ["Compare start durante il lavoro", "Reset Marlin o brownout.", "Controllare alimentazione e log prima del reset.", "Non riprendere: correggere causa, attendere Ready e rifare Home X."],
        ["EXE non parte", "Antivirus, file incompleto o dipendenze di sistema.", "Controllare Event Viewer/antivirus e hash.", "Ripristinare da build verificata; ricreare con build_exe.bat."],
    ]
    add_table(
        doc,
        ["Sintomo", "Cause probabili", "Verifica", "Azione"],
        connection_rows,
        [1500, 2350, 2450, 3060],
        font_size=8.7,
    )

    doc.add_heading("13.2 Homing, fine corsa e movimento", level=2)
    motion_rows = [
        ["X si muove dalla parte sbagliata in Home", "Direzione motore/firmware errata.", "Interrompere immediatamente; osservare direzione G28 X.", "Correggere INVERT_X_DIR o cablaggio secondo firmware; non compensare invertendo solo i pulsanti."],
        ["Dopo Home, +X spinge ancora sul fine corsa", "INVERT_X_DIR e convenzione coordinate non sono coerenti con X_HOME_DIR -1.", "Home deve essere X=0; -X verso switch, +X in allontanamento.", "Correggere INVERT_X_DIR e riflashare Marlin. Non usare coordinate negative e non disabilitare i soft endstop."],
        ["Fine corsa non ferma l’homing", "Pin errato, logica invertita, cavo rotto.", "M119 a riposo e premuto.", "Correggere connettore e X_MIN_ENDSTOP_HIT_STATE prima di riprovare."],
        ["Homing termina subito", "Endstop risulta già TRIGGERED.", "M119 a switch libero.", "Correggere logica, corto o disturbo sul segnale."],
        ["Pre-avvicinamento si ferma prima di G28", "La stima era eccessiva e X-min è stato raggiunto durante la corsa rapida.", "M119 risulta TRIGGERED dopo M120 e M400.", "Non insistere; allontanare il carrello in modo controllato e ripetere con una stima minore."],
        ["Movimento ruvido o rumoroso", "Velocità/accelerazione alte, corrente driver, attrito, disallineamento.", "Provare jog lento senza blade.", "Ridurre parametri; controllare guida, vite/cinghia, corrente TMC e serraggi."],
        ["Perdita di passi", "Coppia insufficiente, urto, accelerazione, surriscaldamento driver.", "Ripetere corsa e confrontare posizione fisica.", "Ridurre carico/parametri; verificare driver e meccanica; rifare Home X."],
        ["Distanza errata ma ripetibile", "M92 X non calibrato.", "Misura esterna su corsa lunga.", "Seguire la calibrazione e verificare dopo M500."],
        ["Errore cambia con direzione", "Backlash o gioco meccanico.", "Misure +X e -X separate.", "Correggere meccanica; non compensare tutto con steps/mm."],
        ["Target fuori limite", "Valore X oltre 0…travel limit.", "Controllare target e limite software.", "Correggere profilo o limite dopo misura reale della corsa."],
        ["Posizione Unknown - home X", "Stop, reset, disconnessione, motori off o calibrazione.", "Controllare evento precedente nel log.", "Eseguire Home X; non forzare l’override salvo diagnostica."],
    ]
    add_table(
        doc,
        ["Sintomo", "Cause probabili", "Verifica", "Azione"],
        motion_rows,
        [1500, 2350, 2450, 3060],
        font_size=8.6,
    )

    doc.add_heading("13.3 Temperatura e heater", level=2)
    thermal_rows = [
        ["Temperatura Unknown", "Nessuna risposta M105, termistore/firmware.", "Controllare stato Ready e log M105.", "Verificare firmware, baud e ingresso termistore."],
        ["Valore assurdo a freddo", "Tipo termistore errato, corto o circuito aperto.", "Confrontare temperatura ambiente; scollegare alimentazione.", "Correggere TEMP_SENSOR_BED e cablaggio prima di attivare il heater."],
        ["Heater non scalda", "Uscita, fusibile, cablaggio, MOSFET, alimentazione.", "Controllare target, tensione e continuità in sicurezza.", "Riparare circuito; non aumentare limiti firmware per mascherare il problema."],
        ["Heating failed", "Aumento temperatura insufficiente.", "Controllare fissaggio termistore, potenza, isolamento.", "Correggere causa fisica; rivalutare parametri Marlin solo dopo misura."],
        ["Thermal runaway", "Sensore staccato, oscillazione, cablaggio o PID.", "Togliere alimentazione e ispezionare.", "Non riavviare ripetutamente; riparare e validare protezione termica."],
        ["Oscillazioni ampie", "PID non adatto, sensore lento, forte dispersione.", "Registrare andamento temperatura.", "Eseguire tuning controllato e verificare adesione del termistore."],
        ["Heater resta attivo dopo Stop", "EMERGENCY_PARSER assente o comando non processato.", "Osservare target e LED uscita.", "Usare arresto fisico; abilitare EMERGENCY_PARSER e verificare M108/M140."],
        ["Vetro con gradienti o rischio shock", "Contatto heater non uniforme o raffreddamento localizzato.", "Controllare uniformità e fissaggio.", "Riscaldare gradualmente; migliorare contatto e isolamento; sostituire vetro danneggiato."],
    ]
    add_table(
        doc,
        ["Sintomo", "Cause probabili", "Verifica", "Azione"],
        thermal_rows,
        [1500, 2350, 2450, 3060],
        font_size=8.6,
    )

    doc.add_heading("13.4 Profili e calibrazione", level=2)
    profile_rows = [
        ["Profilo non parte", "Non connesso, non Ready, non homed, segmento invalido.", "Leggere messaggio e controllare tabella.", "Correggere stato o segmento; verificare target entro limite."],
        ["Profilo si arresta", "Errore Marlin, reset, stop richiesto, timeout.", "Controllare ultime righe del log.", "Eliminare causa; Home X prima di riprendere."],
        ["Attesa temperatura molto lunga", "Potenza insufficiente, dispersione, setpoint alto.", "Confrontare salita °C/min e target.", "Usare Heater Off se anomalo; verificare heater e isolamento."],
        ["M503 non mostra M92", "M503 disabilitato nel firmware.", "Cercare riga M92 nel log.", "Riabilitare M503 o inserire manualmente il valore verificato."],
        ["Calibrazione peggiora", "Misura corta, backlash, slittamento, valore corrente errato.", "Ripetere misure lunghe nella stessa direzione.", "Ripristinare valore precedente, correggere meccanica e ricalibrare."],
        ["M500 dà errore", "EEPROM_SETTINGS non abilitato.", "Controllare risposta Marlin.", "Abilitare EEPROM_SETTINGS o gestire il valore nel firmware."],
        ["JSON non caricato", "File malformato o campi mancanti.", "Aprire il JSON e confrontare struttura.", "Correggere il file o ricreare il profilo dall’app."],
    ]
    add_table(
        doc,
        ["Sintomo", "Cause probabili", "Verifica", "Azione"],
        profile_rows,
        [1500, 2350, 2450, 3060],
        font_size=8.6,
    )

    doc.add_heading("13.5 Come leggere il log seriale", level=2)
    log_rows = [
        ["> comando", "Riga inviata dal PC a Marlin."],
        ["ok", "Marlin ha accettato/completato il comando secondo la sua semantica."],
        ["busy: processing", "Marlin è impegnato in un comando lungo; non indica necessariamente un blocco."],
        ["start", "La scheda si è riavviata. La V3 invalida la posizione e ripete l’handshake."],
        ["Error:", "Comando rifiutato o errore firmware. Non proseguire senza identificarne la causa."],
        ["Heating failed", "Protezione termica: temperatura non aumentata come previsto."],
        ["Thermal runaway", "Protezione termica: instabilità o sensore/heater anomalo."],
        ["kill / halted", "Marlin è in stato arrestato; può essere necessario togliere e ripristinare alimentazione."],
    ]
    add_table(doc, ["Riga", "Interpretazione"], log_rows, [2500, 6860], font_size=9.5)

    doc.add_heading("14. Riferimento G-code", level=1)
    gcode_rows = [
        ["G21", "Unità in millimetri", "No", "Avvio profilo."],
        ["G28 X", "Homing asse X", "Sì", "Richiede fine corsa correttamente configurato."],
        ["G90 / G91", "Posizionamento assoluto / relativo", "No", "Gestiti in sequenze atomiche."],
        ["G1 X… F…", "Movimento X", "Movimento asincrono", "Target verificato contro limite applicativo."],
        ["G4 S…", "Dwell", "Sì", "Pausa segmento profilo."],
        ["M18", "Motori off", "No", "Invalida la posizione nota."],
        ["M92 X…", "Passi/mm asse X", "No", "Usato in calibrazione."],
        ["M105", "Temperatura", "Breve", "Polling associato al proprio ok."],
        ["M108", "Interrompe attesa", "Immediato con emergency parser", "Usato per uscire da M190."],
        ["M112", "Arresto completo", "Immediato con emergency parser", "Stato KILLED: reset o power-cycle obbligatorio; l'app non invia M999 automaticamente."],
        ["M114", "Posizione corrente", "No", "Aggiorna X visualizzata."],
        ["M115", "Informazioni firmware", "No", "Handshake di avvio."],
        ["M119", "Stato fine corsa", "No", "Diagnostica firmware/commissioning."],
        ["M120", "Abilita globalmente i fine corsa", "No", "Protegge la corsa rapida non referenziata verso X-min; resta attivo come limite conservativo."],
        ["M140 S…", "Target bed senza attesa", "No", "S0 spegne il heater."],
        ["M190 S…", "Target bed con attesa", "Sì", "Interrompibile con M108 se supportato."],
        ["M204 T…", "Accelerazione travel", "No", "Usata per asse X senza estrusione."],
        ["M211", "Stato soft endstop", "No", "In commissioning deve risultare abilitato; non usare S0 normalmente."],
        ["M400", "Attende fine movimenti", "Sì", "Conferma completamento meccanico pianificato."],
        ["M410", "Quick stop stepper", "Immediato con emergency parser", "Perdita della posizione; l’app invia poi G90 per uscire da un eventuale movimento relativo."],
        ["M500", "Salva EEPROM", "No", "Memorizza M92 se EEPROM abilitata."],
        ["M503", "Riporta impostazioni", "No", "Legge M92 X attivo."],
    ]
    add_table(
        doc,
        ["Comando", "Funzione", "Può bloccare", "Uso / sicurezza"],
        gcode_rows,
        [1600, 2500, 2000, 3260],
        font_size=8.7,
    )

    doc.add_heading("15. Verifica software V3", level=1)
    doc.add_paragraph(
        "La release include test senza hardware per logica G-code, calibrazione, "
        "profili, impostazioni, protocollo seriale, condizioni di gara, entry point "
        "e protezioni GUI. La build di rilascio deve essere eseguita solo dopo il "
        "superamento della suite pytest."
    )
    add_callout(
        doc,
        "Limite dei test",
        "I test automatici non certificano cablaggio, direzione motore, corrente "
        "driver, fine corsa, termistore, protezioni Marlin o comportamento meccanico. "
        "La validazione con hardware resta obbligatoria.",
        "caution",
    )

    doc.add_heading("16. Fonti tecniche", level=1)
    sources = [
        ("BIGTREETECH SKR Mini E3 V3.0 - manuale ufficiale", "https://github.com/bigtreetech/BIGTREETECH-SKR-mini-E3/blob/master/hardware/BTT%20SKR%20MINI%20E3%20V3.0/Hardware/BTT%20SKR%20MINI%20E3%20V3.0%20user%20manual.pdf"),
        ("Marlin - Configuring Marlin", "https://marlinfw.org/docs/configuration/configuration.html"),
        ("Marlin - Endstops", "https://marlinfw.org/docs/hardware/endstops.html"),
        ("Marlin - M119 Endstop States", "https://marlinfw.org/docs/gcode/M119.html"),
        ("Marlin - M211 Software Endstops", "https://marlinfw.org/docs/gcode/M211.html"),
        ("Marlin - M108 Break and Continue", "https://marlinfw.org/docs/gcode/M108.html"),
        ("Marlin - M105 Report Temperatures", "https://marlinfw.org/docs/gcode/M105.html"),
        ("Marlin - M410 Quickstop", "https://marlinfw.org/docs/gcode/M410.html"),
        ("Marlin - M500 Save Settings", "https://marlinfw.org/docs/gcode/M500.html"),
        ("Marlin - M503 Report Settings", "https://marlinfw.org/docs/gcode/M503.html"),
    ]
    for title, url in sources:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(4)
        set_run_font(p.add_run(f"{title}: "), size=9.5, bold=True, color=NAVY)
        set_run_font(p.add_run(url), size=9, color=BLUE)

    doc.core_properties.title = "Guida Operativa Doctor Blade Controller V3"
    doc.core_properties.subject = "Manuale operativo, sicurezza e troubleshooting"
    doc.core_properties.author = "Doctor Blade Controller Project"
    doc.core_properties.keywords = "doctor blade, SKR Mini E3 V3, Marlin, manuale, troubleshooting"
    doc.core_properties.comments = "Generated for Doctor Blade Controller V3.0.5"

    doc.save(OUTPUT_PATH)
    return OUTPUT_PATH


if __name__ == "__main__":
    print(build_manual())
