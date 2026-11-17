"""Issue の型(.github/ISSUE_TEMPLATE)が YAML として読め、公開の注意と個人情報の注意を持つこと。
11/17 に、記入例の「例: 」の「:」で型が壊れていたのを見落とした。"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

DIR = Path(".github/ISSUE_TEMPLATE")


@pytest.mark.parametrize("name", ["teisei.yml", "tsukaimashita.yml", "config.yml"])
def test_template_is_valid_yaml(name):
    assert isinstance(yaml.safe_load((DIR / name).read_text(encoding="utf-8")), dict)


@pytest.mark.parametrize("name", ["teisei.yml", "tsukaimashita.yml"])
def test_form_warns_that_it_is_public_and_asks_for_no_personal_information(name):
    form = yaml.safe_load((DIR / name).read_text(encoding="utf-8"))
    intro = form["body"][0]["attributes"]["value"]
    assert "公開の場所" in intro and "個人の情報" in intro
    assert all("id" in item for item in form["body"][1:])
