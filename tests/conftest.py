from pathlib import Path

import pytest


@pytest.fixture
def expected_directories() -> set[Path]:
    """Independent acceptance specification, including intermediate directories."""
    return {
        Path(relative)
        for relative in (
            "cdisc_reference",
            "cdisc_reference/cdash",
            "cdisc_reference/cdash/imports",
            "cdisc_reference/cdash/v2.3",
            "cdisc_reference/sdtm",
            "cdisc_reference/sdtm/sdtmig_v3.4",
            "cdisc_reference/adam",
            "cdisc_reference/adam/adamig_v1.3",
            "cdisc_reference/controlled_terminology",
            "cdisc_reference/define_xml",
            "cdisc_reference/define_xml/v2.0",
            "cdisc_reference/define_xml/v2.1",
            "cdisc_reference/define_xml/v2.1/schemas",
            "cdisc_reference/validation_rules",
            "cdisc_reference/validation_rules/cdisc_core",
            "cdisc_reference/validation_rules/custom",
            "cdisc_reference/study_profiles",
        )
    }
