"""HWPX(한글 문서) 읽기/쓰기 공용 모듈.

HWPX는 OCF 기반 zip 컨테이너이고 본문이 평문 XML이라 한컴 오피스 없이 다룰 수 있다.
표의 각 셀은 <hp:cellAddr rowAddr colAddr>로 주소를 가지므로 좌표로 지정해 텍스트를 갈아끼운다.
"""

from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
SECTION = "Contents/section0.xml"
HEADER = "Contents/header.xml"
XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
BLACK = "#000000"

# 업무일지 표를 알아보는 표식. 표 순서에 의존하지 않기 위해 내용으로 찾는다.
DAILY_TABLE_MARKER = "일일 업무일지"
WEEKLY_TABLE_MARKER = "주간 업무일지"


def _register_namespaces(xml_text: str) -> None:
    """원본 루트의 xmlns 선언을 그대로 등록해 ns0: 접두사 오염을 막는다.

    XML 선언(<?xml ... ?>)을 건너뛰고 루트 시작 태그에서만 읽는다. 선언부에서 자르면
    xmlns를 하나도 못 읽어 전체 접두사가 ns0, ns1로 바뀌어 버린다.
    """
    root_start = _root_start(xml_text)
    head = xml_text[root_start : xml_text.find(">", root_start) + 1]
    for prefix, uri in re.findall(r'xmlns:([A-Za-z0-9_.-]+)="([^"]+)"', head):
        ET.register_namespace(prefix, uri)


def _root_start(xml_text: str) -> int:
    decl_end = xml_text.find("?>")
    return xml_text.find("<", decl_end + 2 if decl_end != -1 else 0)


def _root_open_tag(xml_text: str) -> str:
    start = _root_start(xml_text)
    return xml_text[start : xml_text.find(">", start) + 1]


def _read_part(path: str | Path, name: str) -> ET.Element:
    with zipfile.ZipFile(path) as z:
        xml_text = z.read(name).decode("utf-8")
    _register_namespaces(xml_text)
    return ET.fromstring(xml_text)


def load_section(path: str | Path) -> ET.Element:
    """hwpx 본문(section0.xml)을 파싱한다."""
    return _read_part(path, SECTION)


def load_header(path: str | Path) -> ET.Element:
    """hwpx 서식 정의(header.xml)를 파싱한다. 글자 색·크기 같은 charPr가 여기 있다."""
    return _read_part(path, HEADER)


class CharPrPalette:
    """글자 서식(charPr) 팔레트.

    양식의 안내문구는 파란 글씨(textColor=#0000FF)로 되어 있다. 문단을 복제해 내용을
    채우면 그 서식을 그대로 물려받아 결과물도 파랗게 나오므로, 색만 검정으로 바꾼
    동일 서식으로 갈아끼운다. 글꼴·크기는 건드리지 않는다.
    """

    def __init__(self, header_root: ET.Element):
        self.container = header_root.find(".//" + HH + "charProperties")
        if self.container is None:
            raise LookupError("header.xml에서 charProperties를 찾지 못했습니다.")
        self.by_id = {cp.get("id"): cp for cp in self.container.findall(HH + "charPr")}
        self.modified = False
        self._cache: dict[str, str] = {}

    @staticmethod
    def _signature(char_pr: ET.Element) -> str:
        """id와 색을 뺀 나머지 서식. 이게 같으면 색만 다른 같은 서식이다."""
        clone = copy.deepcopy(char_pr)
        clone.set("id", "")
        clone.set("textColor", "")
        return ET.tostring(clone, encoding="unicode")

    def black(self, char_pr_id: str | None) -> str | None:
        """같은 서식의 검은 글씨 charPr id를 돌려준다. 없으면 새로 만들어 등록한다."""
        if char_pr_id is None:
            return None
        source = self.by_id.get(char_pr_id)
        if source is None or (source.get("textColor") or "").upper() == BLACK:
            return char_pr_id
        if char_pr_id in self._cache:
            return self._cache[char_pr_id]

        signature = self._signature(source)
        match = next(
            (
                cp.get("id")
                for cp in self.by_id.values()
                if (cp.get("textColor") or "").upper() == BLACK
                and self._signature(cp) == signature
            ),
            None,
        )

        if match is None:
            match = str(max(int(i) for i in self.by_id) + 1)
            created = copy.deepcopy(source)
            created.set("id", match)
            created.set("textColor", BLACK)
            self.container.append(created)
            self.by_id[match] = created
            self.container.set("itemCnt", str(len(self.by_id)))
            self.modified = True

        self._cache[char_pr_id] = match
        return match


def own_paragraphs(tc: ET.Element) -> list[ET.Element]:
    """셀에 직접 속한 문단. 메모나 중첩표 안쪽 문단은 빼고 본다."""
    sublist = tc.find(HP + "subList")
    return [] if sublist is None else sublist.findall(HP + "p")


def _own(p: ET.Element, tag: str) -> list[ET.Element]:
    """문단 본문에서 해당 태그를 순서대로 모은다.

    subList 아래로는 내려가지 않는다. 거기 있는 글은 메모(주석)나 중첩표의 내용이지
    이 문단의 본문이 아니다. 섞어 읽으면 셀 대조가 통째로 어긋난다.
    """
    found: list[ET.Element] = []

    def walk(node: ET.Element) -> None:
        for child in node:
            if child.tag == HP + "subList":
                continue
            if child.tag == tag:
                found.append(child)
            walk(child)

    walk(p)
    return found


def text_nodes(p: ET.Element) -> list[ET.Element]:
    """문단 본문의 <hp:t>를 순서대로 모은다."""
    return _own(p, HP + "t")


def cell_text(tc: ET.Element, deep: bool = True) -> str:
    """셀 안의 문단 텍스트를 줄바꿈으로 이어 붙인다.

    deep=False면 셀 본문만 읽는다 — 메모와 중첩표의 글을 걷어낸 결과다.
    """
    if deep:
        return "\n".join(
            "".join(t.text or "" for t in p.iter(HP + "t")) for p in tc.iter(HP + "p")
        )
    return "\n".join(
        "".join(t.text or "" for t in text_nodes(p)) for p in own_paragraphs(tc)
    )


def table_cells(
    tbl: ET.Element, include_nested: bool = False
) -> dict[tuple[int, int], ET.Element]:
    """표 안의 셀을 (row, col) -> tc 로 색인한다.

    중첩표의 셀은 기본으로 뺀다. 안쪽 표도 자기 좌표계에서 (0,0)부터 시작하므로
    같이 담으면 바깥 표의 셀을 덮어써 버린다.
    """
    inner: set[int] = set()
    if not include_nested:
        for sub in tbl.iter(HP + "tbl"):
            if sub is not tbl:
                inner.update(id(tc) for tc in sub.iter(HP + "tc"))

    cells = {}
    for tc in tbl.iter(HP + "tc"):
        if id(tc) in inner:
            continue
        addr = tc.find(HP + "cellAddr")
        cells[(int(addr.get("rowAddr")), int(addr.get("colAddr")))] = tc
    return cells


def nested_table(tc: ET.Element) -> ET.Element | None:
    """셀 안에 들어 있는 표. 주간일지의 미션 진도율 분포표가 이 형태다."""
    return next(tc.iter(HP + "tbl"), None)


def find_table(root: ET.Element, marker: str) -> ET.Element:
    """제목 셀(0,0) 내용으로 표를 찾는다. 표 순서에 기대지 않기 위해서다."""
    for tbl in root.iter(HP + "tbl"):
        title = table_cells(tbl).get((0, 0))
        if title is not None and marker in cell_text(title):
            return tbl
    raise LookupError(f"'{marker}' 표를 찾지 못했습니다. 양식 파일이 바뀌었는지 확인하세요.")


def find_daily_table(root: ET.Element) -> ET.Element:
    """붙임1 일일 업무일지 표를 찾는다."""
    return find_table(root, DAILY_TABLE_MARKER)


def find_weekly_table(root: ET.Element) -> ET.Element:
    """붙임2 주간 업무일지 표를 찾는다."""
    return find_table(root, WEEKLY_TABLE_MARKER)


def _paragraph_template(p: ET.Element, palette: CharPrPalette | None) -> ET.Element:
    """문단 하나를 복제용 틀로 다듬는다.

    linesegarray는 한글이 계산해 둔 줄바꿈 레이아웃 캐시다. 텍스트 길이가 바뀌면
    값이 맞지 않으므로 제거하고 한글이 열 때 재계산하도록 둔다.
    run은 첫 번째만 남겨 서식을 보존하되, 안내문구의 파란 글씨는 검정으로 바꾼다.
    """
    template = copy.deepcopy(p)
    for lineseg in template.findall(HP + "linesegarray"):
        template.remove(lineseg)

    runs = template.findall(HP + "run")
    if not runs:
        raise ValueError("문단에 hp:run이 없어 틀로 쓸 수 없습니다.")
    for extra in runs[1:]:
        template.remove(extra)

    run = runs[0]
    for child in list(run):
        run.remove(child)
    if palette is not None:
        black = palette.black(run.get("charPrIDRef"))
        if black is not None:
            run.set("charPrIDRef", black)
    return template


def set_cell_lines(tc: ET.Element, lines: list[str], palette: CharPrPalette | None = None) -> None:
    """셀 내용을 주어진 줄 목록으로 교체한다. 줄 하나가 문단 하나가 된다."""
    sublist = tc.find(HP + "subList")
    paragraphs = sublist.findall(HP + "p")
    if not paragraphs:
        raise ValueError("셀에 문단이 없습니다.")

    template = _paragraph_template(paragraphs[0], palette)
    for p in paragraphs:
        sublist.remove(p)

    for index, line in enumerate(lines or [""]):
        p = copy.deepcopy(template)
        p.set("id", str(index))
        ET.SubElement(p.find(HP + "run"), HP + "t").text = line
        sublist.append(p)


def set_cell(tc: ET.Element, text: str, palette: CharPrPalette | None = None) -> None:
    set_cell_lines(tc, text.split("\n"), palette)


def set_cell_texts(
    tc: ET.Element, texts: list[str | None], palette: CharPrPalette | None = None
) -> None:
    """셀 본문의 <hp:t>를 순서대로 갈아끼운다. 문단 구조와 메모는 건드리지 않는다.

    셀을 새로 짜는 set_cell_lines와 달리, 양식이 미리 잡아 둔 줄바꿈이나 메모(주석)를
    살려야 하는 칸에 쓴다. 주간일지 출석률 칸이 그렇다 — 운영팀 메모가 글자 사이에
    닻을 내리고 있어서 셀을 다시 만들면 사라진다.

    None을 준 자리는 원래 글자를 그대로 둔다. 조각 수가 다르면 양식이 바뀐 것이므로
    조용히 어긋난 값을 쓰지 말고 멈춘다.
    """
    paragraphs = own_paragraphs(tc)
    nodes = [t for p in paragraphs for t in text_nodes(p)]
    if len(nodes) != len(texts):
        raise ValueError(
            f"셀의 글자 조각이 {len(nodes)}개인데 {len(texts)}개를 주었습니다. "
            "양식이 개정됐는지 확인하세요."
        )

    for node, text in zip(nodes, texts):
        if text is not None:
            node.text = text

    if palette is not None:
        for p in paragraphs:
            for run in _own(p, HP + "run"):
                black = palette.black(run.get("charPrIDRef"))
                if black is not None:
                    run.set("charPrIDRef", black)


def take_picture(tc: ET.Element) -> ET.Element | None:
    """셀에 박혀 있는 그림(작성자 칸의 서명 도장)을 복사해 온다.

    셀 내용을 갈아끼우면 그림도 같이 지워지므로, 먼저 떼어 두었다가 다시 넣기 위한 것이다.
    없으면 None을 준다 — 서명이 없는 양식도 그대로 쓸 수 있어야 한다.
    """
    pic = next(tc.iter(HP + "pic"), None)
    return None if pic is None else copy.deepcopy(pic)


def set_cell_parts(
    tc: ET.Element,
    parts: list[str | ET.Element],
    palette: CharPrPalette | None = None,
) -> None:
    """셀을 한 문단으로 채우되, 글과 그림을 준 순서대로 이어 붙인다.

    문자열은 <hp:t>로, ET.Element는 그대로(서명 <hp:pic> 등) 같은 run 안에 들어간다.
    """
    sublist = tc.find(HP + "subList")
    paragraphs = sublist.findall(HP + "p")
    if not paragraphs:
        raise ValueError("셀에 문단이 없습니다.")

    p = _paragraph_template(paragraphs[0], palette)
    for old in paragraphs:
        sublist.remove(old)

    p.set("id", "0")
    run = p.find(HP + "run")
    for part in parts:
        if isinstance(part, str):
            ET.SubElement(run, HP + "t").text = part
        else:
            run.append(part)
    sublist.append(p)


def save(src: str | Path, dst: str | Path, parts: dict[str, ET.Element]) -> None:
    """지정한 XML 항목만 교체하고 나머지는 원본 순서·압축 방식 그대로 다시 담는다.

    mimetype은 OCF 규약상 첫 항목이면서 무압축이어야 하므로 순서를 건드리지 않는다.
    루트 시작 태그는 원본 문자열을 그대로 되살린다. ElementTree는 이 문서에서 실제로
    쓰이지 않는 xmlns 선언을 버리는데, 한글이 그 선언을 기대할 수 있어 위험하기 때문이다.
    """
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        rendered = {}
        for name, root in parts.items():
            original_tag = _root_open_tag(zin.read(name).decode("utf-8"))
            serialized = ET.tostring(root, encoding="unicode")
            serialized = original_tag + serialized[serialized.find(">") + 1 :]
            rendered[name] = (XML_DECL + serialized).encode("utf-8")

        for item in zin.infolist():
            data = rendered.get(item.filename) or zin.read(item.filename)
            info = zipfile.ZipInfo(item.filename, date_time=item.date_time)
            info.compress_type = item.compress_type
            info.external_attr = item.external_attr
            zout.writestr(info, data)
