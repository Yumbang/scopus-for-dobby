"""MathML → LaTeX for Elsevier article XML."""

from xml.etree import ElementTree as ET

from scopus_for_dobby.core.fulltext_bundle import inline
from scopus_for_dobby.core.mathml_latex import mathml_to_latex


def _math(body: str) -> ET.Element:
    xml = f'<math xmlns="http://www.w3.org/1998/Math/MathML">{body}</math>'
    return ET.fromstring(xml)  # noqa: S314


def test_sub_and_identifier_run():
    el = _math(
        "<msub><mi>Q</mi><mn>0</mn></msub><mrow><mi>f</mi><mi>e</mi><mi>e</mi><mi>d</mi></mrow>"
    )
    out = mathml_to_latex(el)
    assert "Q_0" in out
    assert r"\mathrm{feed}" in out


def test_fraction():
    el = _math("<mfrac><mn>1</mn><mn>2</mn></mfrac>")
    assert mathml_to_latex(el) == r"\frac{1}{2}"


def test_piecewise_condition_table_is_sibling():
    """Elsevier: `{ values-table }` then a sibling condition table."""
    el = _math(
        """
        <mrow>
          <msub><mi>Q</mi><mn>0</mn></msub><mo>=</mo>
          <mrow>
            <mo>{</mo>
            <mrow>
              <mtable>
                <mtr><mtd><mn>1</mn></mtd></mtr>
                <mtr><mtd><mn>2</mn></mtd></mtr>
              </mtable>
            </mrow>
          </mrow>
          <mtable>
            <mtr><mtd><mi>a</mi></mtd></mtr>
            <mtr><mtd><mi>b</mi></mtd></mtr>
          </mtable>
        </mrow>
        """
    )
    out = mathml_to_latex(el)
    assert r"\begin{cases}" in out
    assert r"\end{cases}" in out
    assert r"\begin{matrix}" not in out


def test_piecewise_tables_wrapped_in_mrow():
    """Elsevier wraps the two cases tables in an extra mrow after ``{``."""
    el = _math(
        """
        <mrow>
          <mo>{</mo>
          <mrow>
            <mspace/>
            <mtable>
              <mtr><mtd><mn>1</mn></mtd></mtr>
              <mtr><mtd><mn>2</mn></mtd></mtr>
            </mtable>
            <mspace/>
            <mtable>
              <mtr><mtd><mi>a</mi></mtd></mtr>
              <mtr><mtd><mi>b</mi></mtd></mtr>
            </mtable>
          </mrow>
        </mrow>
        """
    )
    out = mathml_to_latex(el)
    assert r"\begin{cases}" in out
    assert "1" in out and r"\mathrm{a}" in out or "a" in out


def test_piecewise_two_tables():
    el = _math(
        """
        <mrow>
          <msub><mi>Q</mi><mn>0</mn></msub>
          <mo>=</mo>
          <mrow>
            <mo>{</mo>
            <mtable>
              <mtr><mtd><msub><mi>Q</mi><mn>1</mn></msub></mtd></mtr>
              <mtr><mtd><mi>Q</mi></mtd></mtr>
            </mtable>
            <mtable>
              <mtr><mtd><mi>a</mi></mtd></mtr>
              <mtr><mtd><mi>b</mi></mtd></mtr>
            </mtable>
          </mrow>
        </mrow>
        """
    )
    out = mathml_to_latex(el)
    assert r"\begin{cases}" in out
    assert r"\end{cases}" in out
    assert "Q_0=" in out.replace(" ", "")


def test_inline_wraps_dollars():
    xml = (
        '<para xmlns:mml="http://www.w3.org/1998/Math/MathML">'
        "Flow "
        "<mml:math><msub><mml:mi>Q</mml:mi><mml:mn>0</mml:mn></msub></mml:math>"
        " rises."
        "</para>"
    )
    para = ET.fromstring(xml)  # noqa: S314
    text = inline(para)
    assert "$Q_0$" in text
    assert "[math]" not in text


def test_display_formula_tagged():
    xml = """
    <display xmlns:mml="http://www.w3.org/1998/Math/MathML">
      <formula id="eqn0001">
        <label>(1)</label>
        <mml:math><msub><mml:mi>Q</mml:mi><mml:mn>0</mml:mn></msub></mml:math>
      </formula>
    </display>
    """
    el = ET.fromstring(xml)  # noqa: S314
    text = inline(el)
    assert "$$" in text
    assert r"\tag{1}" in text
    assert "Q_0" in text
