from decimal import Decimal

from app.services.invoice_ocr import extract_invoice, normalize_tax_id, parse_decimal


def test_normalization_and_decimal_do_not_use_float():
    assert normalize_tax_id("PT 500 115 966") == "500115966"
    assert normalize_tax_id("123") is None
    assert parse_decimal("1.234,56 €") == Decimal("1234.56")
    assert isinstance(parse_decimal("0,10"), Decimal)


def test_filinto_template_does_not_treat_fo_or_as_carfast_work_order():
    result = extract_invoice(
        """FILINTO MOTA
        NIF: 500 115 966
        Fatura: FT 2026/123
        KM: 125 430
        FO / O.R.: 99881
        Total c/ IVA: 123,00 EUR
        Referência  Descrição  Quantidade  Un.  Preço Unit.  Desc.  Valor  IVA
        ABC123  Filtro de óleo  2,00  UN  10,00  0,00  20,00  23,00
        Total 24,60
        """
    )
    assert result.supplier_code == "filinto_mota"
    assert result.supplier_tax_id == "500115966"
    assert result.fields["km"] == "125430"
    assert result.fields["total_with_vat"] == Decimal("123.00")
    assert "work_order" not in result.fields
    assert result.lines[0].reference == "ABC123"
    assert result.lines[0].quantity == Decimal("2.00")


def test_gamobar_explicit_work_order_and_serialization():
    result = extract_invoice(
        """GAMOBAR
        NIPC 500112967
        Folha de obra: WO-42
        Descrição | Quantidade | Unidade | Preço | Valor | IVA
        Alinhamento | 1 | UN | 35,50 | 35,50 | 23
        Total a pagar: 43,67
        """
    )
    assert result.supplier_code == "gamobar"
    assert result.fields["work_order"] == "WO-42"
    assert result.lines[0].description == "Alinhamento"
    assert result.serializable()["fields"]["total_with_vat"] == "43.67"


def test_absent_fields_are_not_invented_and_vertical_text_is_ignored():
    result = extract_invoice(
        """NIF: 500112967
        Descrição  Quantidade  Preço  Valor
        M A R C A D E A G U A
        Serviço diagnóstico  1  25,00  25,00
        Total 25,00
        """
    )
    assert "km" not in result.fields
    assert "invoice_number" not in result.fields
    assert len(result.lines) == 1
