"""Elsevier XML → markdown bundle."""

from __future__ import annotations

from pathlib import Path

from scopus_for_dobby.core import fulltext as ft
from scopus_for_dobby.core.fulltext_bundle import materialize

XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<full-text-retrieval-response xmlns:ce="http://www.elsevier.com/xml/common/dtd">
  <coredata><eid>2-s2.0-testbundle</eid><title>Bundle Paper</title></coredata>
  <objects>
    <object ref="gr1" type="IMAGE-DOWNSAMPLED">https://api.elsevier.com/content/object/eid/1-s2.0-x-gr1.jpg</object>
  </objects>
  <originalText>
    <ce:article>
      <ce:floats>
        <ce:figure id="fig0001">
          <ce:label>Fig. 1</ce:label>
          <ce:caption><ce:simple-para>A flowchart.</ce:simple-para></ce:caption>
          <ce:link locator="gr1"/>
        </ce:figure>
        <ce:table id="tbl0001">
          <ce:label>Table 1</ce:label>
          <ce:caption><ce:simple-para>Metrics.</ce:simple-para></ce:caption>
          <ce:tgroup cols="2">
            <ce:thead><ce:row>
              <ce:entry>Var</ce:entry><ce:entry>R2</ce:entry>
            </ce:row></ce:thead>
            <ce:tbody><ce:row>
              <ce:entry>Flow</ce:entry><ce:entry>1.00</ce:entry>
            </ce:row></ce:tbody>
          </ce:tgroup>
        </ce:table>
      </ce:floats>
      <ce:head>
        <ce:title>Bundle Paper</ce:title>
        <ce:author-group>
          <ce:author>
            <ce:given-name>Ada</ce:given-name>
            <ce:surname>Lovelace</ce:surname>
            <ce:cross-ref refid="aff1"/>
            <ce:cross-ref refid="fn1"/>
          </ce:author>
          <ce:affiliation id="aff1">University of Notes</ce:affiliation>
          <ce:footnote id="fn1"><ce:note-para>These authors contributed equally to this work.</ce:note-para></ce:footnote>
        </ce:author-group>
        <ce:abstract class="author">
          <ce:abstract-sec><ce:simple-para>An abstract sentence.</ce:simple-para></ce:abstract-sec>
        </ce:abstract>
        <ce:keywords class="keyword">
          <ce:keyword>membranes</ce:keyword>
        </ce:keywords>
      </ce:head>
      <ce:body>
        <ce:sections>
          <ce:section id="sec1">
            <ce:section-title>Introduction</ce:section-title>
            <ce:para>Reverse osmosis is the dominant membrane process.</ce:para>
          </ce:section>
          <ce:section id="sec2">
            <ce:section-title>Materials and methods</ce:section-title>
            <ce:para>We modelled a plant.</ce:para>
            <ce:section id="sec2a">
              <ce:section-title>Numerical model</ce:section-title>
              <ce:para>The mass balance closed.</ce:para>
            </ce:section>
          </ce:section>
        </ce:sections>
      </ce:body>
    </ce:article>
  </originalText>
</full-text-retrieval-response>
"""


def test_materialize_writes_tree(tmp_path):
    dest = tmp_path / "bundle"
    fake_jpeg = b"\xff\xd8\xff fake"

    def fetch(url: str) -> bytes:
        assert "gr1" in url
        return fake_jpeg

    manifest = materialize(XML, dest, eid="2-s2.0-testbundle", doi="10.1/x", fetch_object=fetch)
    assert (dest / "xml" / "article.xml").is_file()
    assert (dest / "head.md").read_text().startswith("# Bundle Paper")
    assert "Ada Lovelace" in (dest / "head.md").read_text()
    assert "fn1" in (dest / "head.md").read_text()
    intro = dest / "sections" / "01-introduction.md"
    methods = dest / "sections" / "02-materials-and-methods.md"
    nested = dest / "sections" / "02.01-numerical-model.md"
    assert intro.is_file()
    assert "Reverse osmosis" in intro.read_text()
    assert methods.is_file()
    assert nested.is_file()
    assert "mass balance" in nested.read_text()
    assert (dest / "tables" / "tbl0001.md").read_text().startswith("# Table 1")
    assert "Flow" in (dest / "tables" / "tbl0001.md").read_text()
    assert (dest / "figures" / "fig0001.jpg").read_bytes() == fake_jpeg
    assert "A flowchart" in (dest / "figures" / "fig0001.caption.md").read_text()
    assert manifest["sections"][0]["title"] == "Introduction"
    assert manifest["sections"][1]["children"][0]["title"] == "Numerical model"
    assert manifest["figures"][0]["file"] == "figures/fig0001.jpg"


def test_legacy_xml_migrates(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "CONFIG_DIR", tmp_path)
    eid = "2-s2.0-legacy"
    (tmp_path / "fulltext").mkdir()
    (tmp_path / "fulltext" / f"{eid}.xml").write_text(XML, encoding="utf-8")
    assert ft.has_cache(eid)
    assert not (tmp_path / "fulltext" / f"{eid}.xml").exists()
    assert ft.source_path(eid).is_file()
    assert ft.source_path(eid).name == "article.xml"


def test_source_xml_moves_into_xml_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "CONFIG_DIR", tmp_path)
    eid = "2-s2.0-oldbundle"
    d = tmp_path / "fulltext" / eid
    d.mkdir(parents=True)
    (d / "source.xml").write_text("<xml/>", encoding="utf-8")
    ft.migrate_cache_layout()
    assert not (d / "source.xml").exists()
    assert (d / "xml" / "article.xml").read_text() == "<xml/>"


def test_cache_hit_builds_manifest_without_http(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr("scopus_for_dobby.core.fulltext_bundle.download_object", lambda url: b"img")
    eid = "2-s2.0-testbundle"
    ft.write_source(eid, XML)
    row = ft.fetch_one(
        {"eid": eid, "doi": "10.1/x"},
        request=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no http")),
    )
    assert row["status"] == ft.STATUS_CACHED
    assert (Path(row["path"]) / "manifest.json").is_file()
    assert "Introduction" in row["outline"]


SECTION_LIST_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<full-text-retrieval-response xmlns:ce="http://www.elsevier.com/xml/common/dtd">
  <coredata><eid>2-s2.0-list</eid><title>List Paper</title></coredata>
  <originalText>
    <ce:article>
      <ce:sections>
        <ce:section id="s1">
          <ce:section-title>Methods</ce:section-title>
          <ce:para>The protocol ran as follows.</ce:para>
          <ce:list>
            <ce:list-item><ce:label>1.</ce:label><ce:para>Soak the membrane.</ce:para></ce:list-item>
            <ce:list-item><ce:label>2.</ce:label><ce:para>Rinse for 10 min.</ce:para></ce:list-item>
          </ce:list>
          <ce:para>Samples were then analysed.</ce:para>
        </ce:section>
      </ce:sections>
      <ce:bibliography>
        <ce:bibliography-sec>
          <ce:bib-reference id="b1">
            <ce:label>[1]</ce:label>
            <ce:textref>Cho et al., Water Research 180 (2020) 115873.</ce:textref>
          </ce:bib-reference>
        </ce:bibliography-sec>
      </ce:bibliography>
    </ce:article>
  </originalText>
</full-text-retrieval-response>
"""


def test_section_level_list_survives(tmp_path):
    """A ce:list hung straight off ce:section is content, not markup noise."""
    manifest = materialize(
        SECTION_LIST_XML, tmp_path, eid="2-s2.0-list", fetch_object=lambda u: None
    )
    body = (tmp_path / manifest["sections"][0]["file"]).read_text()
    assert "- Soak the membrane." in body
    assert "- Rinse for 10 min." in body
    # The prose either side must not silently run together.
    assert body.index("protocol ran") < body.index("Soak") < body.index("analysed")


def test_bibliography_is_rendered(tmp_path):
    manifest = materialize(
        SECTION_LIST_XML, tmp_path, eid="2-s2.0-list", fetch_object=lambda u: None
    )
    assert manifest["references"] == "references.md"
    assert "[1] Cho et al." in (tmp_path / "references.md").read_text()


def test_no_bibliography_reports_none(tmp_path):
    manifest = materialize(XML, tmp_path, eid="2-s2.0-testbundle", fetch_object=lambda u: None)
    assert manifest["references"] is None
    assert not (tmp_path / "references.md").exists()


def test_pipe_in_a_cell_does_not_open_a_column():
    import xml.etree.ElementTree as ET

    from scopus_for_dobby.core.fulltext_bundle import _table_md

    table = ET.fromstring(  # noqa: S314
        "<table id='tbl1'><label>Table 1</label><tgroup><tbody>"
        "<row><entry>Stream</entry><entry>Flux</entry></row>"
        "<row><entry>A|B</entry><entry>3</entry></row>"
        "</tbody></tgroup></table>"
    )
    md = _table_md(table)
    rows = [ln for ln in md.splitlines() if ln.startswith("|")]
    assert rows[-1] == r"| A\|B | 3 |"
    # Header, separator, and one body row — all two columns wide.
    assert all(ln.count("|") - ln.count(r"\|") == 3 for ln in rows)


def test_figure_download_failure_does_not_lose_the_article(tmp_path, monkeypatch):
    import requests

    from scopus_for_dobby.core import fulltext_bundle as fb

    def boom(*a, **k):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(fb, "api_get_raw", boom)
    manifest = materialize(XML, tmp_path, eid="2-s2.0-testbundle")
    assert manifest["figures"][0]["file"] is None
    assert (tmp_path / "head.md").is_file()
    assert manifest["sections"]
