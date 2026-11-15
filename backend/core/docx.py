"""core/docx.py — 最小 DOCX 生成器（纯标准库）

为什么自己做：报告要能交付，而端侧不能 pip 装 python-docx。DOCX 本质是一个 zip + 几段 XML，
只用到"标题 / 段落 / 表格"三种结构时，手写比引依赖更稳。

生成结构：
  [Content_Types].xml          声明部件类型
  _rels/.rels                  指向主文档
  word/document.xml            正文
  word/styles.xml              中文字体与标题样式（宋体小四、1.5 倍行距）
  docProps/core.xml            标题与作者

不做的事：页眉页脚、编号、图片、目录域、样式继承。需要这些就走"导出去 WPS 再排版"。
"""
import zipfile
from xml.sax.saxutils import escape

W_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles %s>
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="宋体"/>
<w:sz w:val="24"/><w:szCs w:val="24"/>
</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>
<w:spacing w:line="360" w:lineRule="auto"/>
</w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:before="240" w:after="120"/><w:jc w:val="center"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:before="180" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
</w:styles>""" % W_NS


def _p(text, style=None, bold=False, size=None, align=None):
    ppr = ''
    inner = ''
    if style:
        ppr += '<w:pStyle w:val="%s"/>' % style
    if align:
        ppr += '<w:jc w:val="%s"/>' % align
    if bold:
        inner += '<w:b/>'
    if size:
        inner += '<w:sz w:val="%d"/>' % int(size * 2)
    run = '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (
        ('<w:rPr>%s</w:rPr>' % inner) if inner else '', escape(text))
    return '<w:p>%s%s</w:p>' % (('<w:pPr>%s</w:pPr>' % ppr) if ppr else '', run)


def _table(headers, rows, widths=None):
    def cell(txt, bold=False, w=None):
        wpr = '<w:tcW w:w="%d" w:type="dxa"/>' % w if w else ''
        return ('<w:tc><w:tcPr>%s</w:tcPr>%s</w:tc>'
                % (wpr, _p(str(txt), bold=bold, size=10)))
    out = ['<w:tbl><w:tblPr>'
           '<w:tblW w:w="0" w:type="auto"/>'
           '<w:tblLayout w:type="fixed"/>'
           '<w:tblBorders>'
           '<w:top w:val="single" w:sz="4" w:color="BFBFBF"/>'
           '<w:left w:val="single" w:sz="4" w:color="BFBFBF"/>'
           '<w:bottom w:val="single" w:sz="4" w:color="BFBFBF"/>'
           '<w:right w:val="single" w:sz="4" w:color="BFBFBF"/>'
           '<w:insideH w:val="single" w:sz="4" w:color="BFBFBF"/>'
           '<w:insideV w:val="single" w:sz="4" w:color="BFBFBF"/>'
           '</w:tblBorders></w:tblPr>']
    w = widths or [2000] * len(headers)
    # tblGrid 是 OOXML 的必需元素，缺了严格的解析器（含 python-docx、部分 WPS）会报错
    out.append('<w:tblGrid>%s</w:tblGrid>'
               % ''.join('<w:gridCol w:w="%d"/>' % w[i] for i in range(len(headers))))
    out.append('<w:tr>%s</w:tr>' % ''.join(cell(h, True, w[i]) for i, h in enumerate(headers)))
    for r in rows:
        out.append('<w:tr>%s</w:tr>' % ''.join(cell(c, False, w[i]) for i, c in enumerate(r)))
    out.append('</w:tbl>')
    return ''.join(out)


def build(path, blocks, title='报告'):
    """blocks: [('title'|'h1'|'h2'|'p'|'small'|'table', payload)]"""
    body = []
    for kind, payload in blocks:
        if kind == 'title':
            body.append(_p(payload, 'Title'))
        elif kind == 'h1':
            body.append(_p(payload, 'Heading1'))
        elif kind == 'h2':
            body.append(_p(payload, 'Heading2'))
        elif kind == 'small':
            body.append(_p(payload, size=9))
        elif kind == 'table':
            body.append(_table(payload[0], payload[1], payload[2] if len(payload) > 2 else None))
        else:
            body.append(_p(payload))

    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document %s><w:body>%s'
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1440" w:right="1418" w:bottom="1440" w:left="1418"/></w:sectPr>'
                '</w:body></w:document>') % (W_NS, ''.join(body))

    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:title>%s</dc:title><dc:creator>培训教学质量评估系统</dc:creator>'
            '</cp:coreProperties>') % escape(title)

    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', CONTENT_TYPES)
        z.writestr('_rels/.rels', RELS)
        z.writestr('word/_rels/document.xml.rels', DOC_RELS)
        z.writestr('word/styles.xml', STYLES)
        z.writestr('word/document.xml', document)
        z.writestr('docProps/core.xml', core)
    return path
