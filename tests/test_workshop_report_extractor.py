from app.services.workshop_report_extractor import _extract_values_from_text


def test_fault_reading_accepts_standard_and_extended_dtc_codes():
    text = """
    DTC
    Descricao
    Estado
    B1011
    Defeito de iluminacao da matricula
    fugitiva
    P02ED:21
    Debito de ar inferior a instrucao
    permanente
    """

    values = _extract_values_from_text(text, "fault_reading")

    assert values["faults_found"] == "Sim"
    assert "B1011 - Defeito de iluminacao da matricula (fugitiva)" in values["faults"]
    assert "P02ED:21 - Debito de ar inferior a instrucao (permanente)" in values["faults"]


def test_remote_download_extracts_ecu_identification_fields():
    text = """
    Referencia ISO
    00 01 50 38 19
    Referencia do material
    9824601180
    Versao de material
    00
    Referencia do software
    9698770180
    Numero de serie da peca
    353335384541333032363031393420
    fetching date
    06 / 11 / 2025
    Edicao do software
    00.00
    referencia homologacao EOBD
    96 408 716 80
    """

    values = _extract_values_from_text(text, "remote_download")

    assert values == {
        "iso_reference": "00 01 50 38 19",
        "hardware_reference": "9824601180",
        "hardware_version": "00",
        "software_reference": "9698770180",
        "part_serial_number": "353335384541333032363031393420",
        "software_edition": "00.00",
        "eobd_approval_reference": "96 408 716 80",
        "remote_download_date": "06 / 11 / 2025",
    }


def test_path_only_report_is_not_presented_as_missing_extraction():
    text = """
    Caminho: Selecao automatica > Funcoes de manutencao >
    Restauracao do oleo > limiar de manutencao >
    Submodelo: JUMPER 3 Euro 6
    """

    values = _extract_values_from_text(text, "maintenance_programming")

    assert values == {
        "machine_path_only": (
            "Selecao automatica > Funcoes de manutencao > Restauracao do oleo > "
            "limiar de manutencao > (o PDF nao contem valores tecnicos)"
        )
    }
